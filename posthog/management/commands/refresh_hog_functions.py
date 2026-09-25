import json
import time
from typing import Any

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

import structlog

from posthog.cdp.filters import DATA_WAREHOUSE_SOURCES, RUNTIME_CONTRACT
from posthog.cdp.validation import generate_template_bytecode
from posthog.dataclasses import frozen

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)


@frozen
class InputRefresh:
    stamped: int
    skipped: int


def refresh_input_templates(hog_function: HogFunction) -> InputRefresh:
    """
    Recompile every hog input template from its stored value, the way a save through the API does,
    and stamp it with the runtime it was checked against. The model's save only recompiles filters.

    An input the current guard refuses keeps its stored bytecode and gets no stamp: it fails at
    run time exactly as before, and an unstamped failure is classified as the owner's to fix.
    """
    is_dwh_source = (hog_function.filters or {}).get("source") in DATA_WAREHOUSE_SOURCES
    stamped = 0
    skipped = 0
    for store_name in ("inputs", "encrypted_inputs"):
        store: dict[str, Any] = getattr(hog_function, store_name) or {}
        changed = False
        for key, item in store.items():
            if not isinstance(item, dict) or item.get("templating", "hog") != "hog" or "bytecode" not in item:
                continue
            try:
                bytecode = generate_template_bytecode(
                    item.get("value"),
                    set(),
                    function_type=hog_function.type,
                    is_dwh_source=is_dwh_source,
                    validate_globals=True,
                )
            except Exception as e:
                skipped += 1
                logger.warning(
                    "hog_function_input_template_no_longer_compiles",
                    hog_function_id=str(hog_function.id),
                    team_id=hog_function.team_id,
                    input_key=key,
                    error=str(e),
                )
                continue
            # The compiler returns opcode enums; the stored form is plain JSON, like a save writes it.
            item["bytecode"] = json.loads(json.dumps(bytecode))
            item["bytecode_contract"] = RUNTIME_CONTRACT
            stamped += 1
            changed = True
        if changed:
            setattr(hog_function, store_name, store)
    return InputRefresh(stamped=stamped, skipped=skipped)


class Command(BaseCommand):
    help = (
        "Refresh HogFunctions (both enabled and disabled) by re-saving them, which recompiles their "
        "filters and their hog input templates and stamps both with the current runtime contract"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", type=int, help="Team ID to refresh HogFunctions for (if not provided, processes all teams)"
        )
        parser.add_argument(
            "--hog-function-id",
            type=str,
            help="Specific HogFunction ID to refresh (if provided, only this function is processed)",
        )
        parser.add_argument(
            "--type",
            action="append",
            choices=["destination", "internal_destination"],
            help="Function type to refresh. Repeatable. Defaults to destination.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Recompile and report what would be stamped or skipped, without saving anything.",
        )

    def handle(self, *args, **options):
        start_time = time.time()
        total_processed = 0
        total_updated = 0
        error_count = 0
        inputs_stamped = 0
        inputs_skipped = 0

        team_id = options.get("team_id")
        hog_function_id = options.get("hog_function_id")
        types = options.get("type") or ["destination"]
        dry_run: bool = options.get("dry_run", False)
        page_size = 1000

        self.stdout.write("Starting HogFunction refresh..." + (" (dry run, nothing is saved)" if dry_run else ""))

        queryset = HogFunction.objects.filter(deleted=False, type__in=types).select_related("team")

        if hog_function_id:
            queryset = queryset.filter(id=hog_function_id)
            self.stdout.write(f"Processing single HogFunction: {hog_function_id}")
        elif team_id:
            queryset = queryset.filter(team_id=team_id)
            self.stdout.write(f"Processing HogFunctions for team: {team_id}")
        else:
            self.stdout.write("Processing HogFunctions for all teams")

        total_count = queryset.count()
        self.stdout.write(f"Found {total_count} HogFunctions to process (includes both enabled and disabled functions)")

        if total_count == 0:
            self.stdout.write(self.style.WARNING("No HogFunctions found matching criteria"))
            return

        paginator = Paginator(queryset.order_by("id"), page_size)

        for page_num in paginator.page_range:
            page = paginator.page(page_num)

            self.stdout.write(
                f"Processing page {page_num}/{paginator.num_pages} ({len(page.object_list)} functions)..."
            )

            for hog_function in page.object_list:
                try:
                    total_processed += 1
                    refreshed = refresh_input_templates(hog_function)
                    inputs_stamped += refreshed.stamped
                    inputs_skipped += refreshed.skipped
                    if dry_run:
                        continue
                    hog_function.save()
                    total_updated += 1
                except Exception as e:
                    error_count += 1
                    logger.error(
                        "Error refreshing HogFunction",
                        hog_function_id=hog_function.id,
                        error=str(e),
                        exc_info=True,
                    )

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Dry run' if dry_run else 'Refresh'} completed in {duration:.2f}s. "
                f"Processed: {total_processed}, "
                f"Updated: {total_updated}, "
                f"Inputs stamped: {inputs_stamped}, "
                f"Inputs skipped: {inputs_skipped}, "
                f"Errors: {error_count}"
            )
        )
