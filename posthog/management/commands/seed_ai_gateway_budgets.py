"""Seed per-team spend budgets on the Go ai-gateway for the products it routes.

A routed sandbox run is bounded per run by its scoped token's cap, but nothing
bounds how many runs a team starts. This sets a windowed ceiling per (team,
product) so the aggregate is bounded too.

The product list is derived from SANDBOX_AI_GATEWAY_PRODUCTS rather than
restated here, so it cannot name a product that is not routed (a budget nothing
binds to) or miss one that is.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.llm.gateway_internal_client import (
    AIGatewayBudgetSuperseded,
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    set_budget,
)

# The gateway budgets a "product" attribution node; a routed run's token pins one.
BUDGET_SCOPE_TYPE = "product"

DEFAULT_LIMIT_USD = "500"
DEFAULT_WINDOW_SECONDS = 86400


def routed_products(products_csv: str) -> list[str]:
    """The distinct products the allowlist routes, with scout skill qualifiers dropped.

    An entry may narrow a product to one scout skill (``signals_scout:web-analytics``).
    The budget key is the product node, which carries no skill, so both forms seed
    the same product and a qualified entry must not become its own budget.
    """
    products = {entry.strip().split(":", 1)[0] for entry in products_csv.split(",") if entry.strip()}
    return sorted(p for p in products if p)


class Command(BaseCommand):
    help = "Seed per-team, per-product spend budgets on the Go ai-gateway for routed products"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            action="append",
            dest="team_ids",
            required=True,
            help="Team to seed. Repeat for several teams.",
        )
        parser.add_argument(
            "--limit-usd",
            default=DEFAULT_LIMIT_USD,
            help=f"Ceiling per team per product, in dollars (default {DEFAULT_LIMIT_USD}).",
        )
        parser.add_argument(
            "--window-seconds",
            type=int,
            default=DEFAULT_WINDOW_SECONDS,
            help=f"Window the ceiling applies over (default {DEFAULT_WINDOW_SECONDS}).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Print what would be written.")

    def handle(self, *args, **options):
        products_csv = settings.SANDBOX_AI_GATEWAY_PRODUCTS or ""
        products = routed_products(products_csv)
        if not products:
            raise CommandError(
                "SANDBOX_AI_GATEWAY_PRODUCTS is empty — no products are routed, so there is nothing to budget"
            )

        team_ids = options["team_ids"]
        limit_usd = options["limit_usd"]
        window_seconds = options["window_seconds"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Routed products: {', '.join(products)}")
        self.stdout.write(f"Teams: {', '.join(str(t) for t in team_ids)}")
        self.stdout.write(f"Budget: ${limit_usd} per {window_seconds}s per team per product")

        failures = 0
        for team_id in team_ids:
            for product in products:
                target = f"team {team_id} {BUDGET_SCOPE_TYPE}/{product}"
                if dry_run:
                    self.stdout.write(f"[dry-run] would set {target}")
                    continue
                try:
                    budget = set_budget(
                        team_id=team_id,
                        scope_type=BUDGET_SCOPE_TYPE,
                        scope_value=product,
                        limit_usd=limit_usd,
                        window_seconds=window_seconds,
                    )
                except AIGatewayNotConfigured as exc:
                    raise CommandError(str(exc)) from exc
                except AIGatewayBudgetSuperseded as exc:
                    # The row committed but a concurrent write's limit is what enforces.
                    # Not a failure to retry: re-running cannot beat the newer value.
                    self.stdout.write(self.style.WARNING(f"superseded, left alone: {target} ({exc})"))
                    continue
                except AIGatewayInternalError as exc:
                    failures += 1
                    self.stderr.write(self.style.ERROR(f"failed: {target} ({exc})"))
                    continue

                # The gateway sanitizes scope_value on write exactly as admission
                # sanitizes a request's node. A value that came back different would
                # be keyed on a string no request ever produces, so the budget would
                # sit there enforcing nothing.
                if budget.scope_value != product:
                    failures += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"stored scope_value {budget.scope_value!r} differs from {product!r}; "
                            "this budget would never bind"
                        )
                    )
                    continue
                self.stdout.write(self.style.SUCCESS(f"set {target} -> ${budget.limit_usd}/{budget.window_seconds}s"))

        if failures:
            raise CommandError(f"{failures} budget write(s) failed")
