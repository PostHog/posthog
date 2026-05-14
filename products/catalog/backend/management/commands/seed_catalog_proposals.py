"""Seed the catalog with dummy proposals for UI testing.

Creates a handful of CatalogNode rows with status=proposed/drift, a
CatalogMetric tied to one of them, and a few CatalogRelationship rows in
proposed/rejected status — enough to populate every category in the proposals
inbox.

Idempotent: rows are upserted by (team, kind, name) for nodes, (team, name) for
metrics, and (team, source, target, columns, kind) for relationships. Safe to
re-run.

    ./manage.py seed_catalog_proposals --team-id 5
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models.team import Team

from products.catalog.backend.models import CatalogMetric, CatalogNode, CatalogRelationship


def _upsert_node(
    *,
    team_id: int,
    kind: str,
    name: str,
    status: str,
    business_domain: str | None = None,
    semantic_role: str | None = None,
    synthetic_description: str | None = None,
    confidence: float | None = None,
    tags: list[str] | None = None,
) -> CatalogNode:
    node, _ = CatalogNode.objects.update_or_create(
        team_id=team_id,
        kind=kind,
        name=name,
        defaults={
            "status": status,
            "business_domain": business_domain,
            "semantic_role": semantic_role,
            "synthetic_description": synthetic_description,
            "confidence": confidence,
            "generator_model": "claude-opus-4-7",
            "tags": tags or [],
        },
    )
    return node


def _upsert_relationship(
    *,
    team_id: int,
    source: CatalogNode,
    target: CatalogNode,
    kind: str,
    status: str,
    confidence: float,
    reasoning: str,
) -> CatalogRelationship:
    rel, _ = CatalogRelationship.objects.update_or_create(
        team_id=team_id,
        source_node=source,
        source_column=None,
        target_node=target,
        target_column=None,
        kind=kind,
        defaults={
            "status": status,
            "confidence": confidence,
            "reasoning": reasoning,
            "generator_model": "claude-opus-4-7",
        },
    )
    return rel


class Command(BaseCommand):
    help = "Seed dummy CatalogNode/CatalogRelationship/CatalogMetric rows for testing the proposals inbox UI."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed proposals for.")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]
        if not Team.objects.filter(pk=team_id).exists():
            raise CommandError(f"Team {team_id} does not exist")

        # New definitions (status=proposed) — one of each interesting node kind.
        warehouse = _upsert_node(
            team_id=team_id,
            kind=CatalogNode.Kind.WAREHOUSE_TABLE,
            name="stripe_subscription",
            status=CatalogNode.Status.PROPOSED,
            business_domain="billing",
            semantic_role="fact",
            synthetic_description=(
                "Stripe subscription records — one row per active or historical subscription. "
                "Use for revenue, churn, and seat-count analyses."
            ),
            confidence=0.92,
            tags=["stripe", "billing", "canonical"],
        )
        saved_query = _upsert_node(
            team_id=team_id,
            kind=CatalogNode.Kind.SAVED_QUERY,
            name="active_subscriptions_view",
            status=CatalogNode.Status.PROPOSED,
            business_domain="billing",
            semantic_role="dimension",
            synthetic_description=(
                "Filtered view over stripe_subscription where status='active'. "
                "Cheaper to join than the raw table for live counts."
            ),
            confidence=0.78,
            tags=["derived", "billing"],
        )
        event_def = _upsert_node(
            team_id=team_id,
            kind=CatalogNode.Kind.EVENT_DEFINITION,
            name="signup_completed",
            status=CatalogNode.Status.PROPOSED,
            business_domain="product_usage",
            semantic_role="event_source",
            synthetic_description=(
                "Fired when a new user finishes the signup form. The agent inferred this is the "
                "canonical signup event from 23 insights filtering on it."
            ),
            confidence=0.88,
            tags=["onboarding", "high-volume"],
        )

        # Metric proposal — bound to a CatalogNode(kind=metric).
        metric_node = _upsert_node(
            team_id=team_id,
            kind=CatalogNode.Kind.METRIC,
            name="arr",
            status=CatalogNode.Status.PROPOSED,
            business_domain="billing",
            semantic_role="measure",
            synthetic_description=(
                "Annual Recurring Revenue. Sum of active subscription amount normalized to a yearly cadence."
            ),
            confidence=0.95,
            tags=["finance", "board-metric"],
        )
        CatalogMetric.objects.update_or_create(
            team_id=team_id,
            name="arr",
            defaults={
                "description": "Annual Recurring Revenue across all active Stripe subscriptions.",
                "definition": {
                    "kind": "HogQLQuery",
                    "query": (
                        "SELECT SUM(\n"
                        "    CASE\n"
                        "        WHEN billing_interval = 'month' THEN amount * 12\n"
                        "        WHEN billing_interval = 'year' THEN amount\n"
                        "    END\n"
                        ") AS arr\n"
                        "FROM stripe_subscription\n"
                        "WHERE status = 'active'"
                    ),
                },
            },
        )

        # Drift alert — a node the agent thinks went stale.
        drift_node = _upsert_node(
            team_id=team_id,
            kind=CatalogNode.Kind.SAVED_QUERY,
            name="revenue_legacy_view",
            status=CatalogNode.Status.DRIFT,
            business_domain="billing",
            semantic_role="fact",
            synthetic_description=(
                "Legacy revenue view. The agent flagged it after Stripe added a `discount_amount` "
                "column that this view doesn't subtract — numbers diverge from `revenue` by ~3%."
            ),
            confidence=0.84,
            tags=["legacy", "billing"],
        )

        # Relationship proposals — one proposed, one rejected (audit fixture).
        _upsert_relationship(
            team_id=team_id,
            source=metric_node,
            target=warehouse,
            kind=CatalogRelationship.Kind.DEPENDS_ON,
            status=CatalogRelationship.Status.PROPOSED,
            confidence=0.97,
            reasoning="The arr metric's HogQL query references stripe_subscription directly.",
        )
        _upsert_relationship(
            team_id=team_id,
            source=event_def,
            target=warehouse,
            kind=CatalogRelationship.Kind.SAME_ENTITY,
            status=CatalogRelationship.Status.PROPOSED,
            confidence=0.71,
            reasoning=(
                "94% of distinct_ids that fire signup_completed within 7 days appear in stripe_subscription "
                "as customer_email — they likely identify the same person."
            ),
        )
        _upsert_relationship(
            team_id=team_id,
            source=saved_query,
            target=drift_node,
            kind=CatalogRelationship.Kind.LINEAGE,
            status=CatalogRelationship.Status.REJECTED,
            confidence=0.55,
            reasoning="Initially proposed as a lineage edge; rejected because the two views are independent rewrites.",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded proposals for team {team_id}: "
                f"4 proposed nodes, 1 metric, 1 drift node, 2 proposed relationships, 1 rejected relationship."
            )
        )
