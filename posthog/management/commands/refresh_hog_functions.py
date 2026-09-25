import json
import time
from typing import Any

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

import structlog

from posthog.cdp.filters import DATA_WAREHOUSE_SOURCES, RUNTIME_CONTRACT, compile_filters_bytecode
from posthog.cdp.validation import generate_template_bytecode
from posthog.dataclasses import frozen

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)


@frozen
class Refresh:
    stamped: int
    skipped: int


def _compilable_value(value: Any, item_type: str | None) -> Any:
    """The part of a stored value the save path compiles.

    An email input carries the visual editor's design beside the body, and the save path leaves it
    out. Compiling it here would fail on designs the template parser refuses, and the input would
    lose its stamp for a reason the save path never had.
    """
    if item_type in ("email", "native_email") and isinstance(value, dict):
        return {key: value[key] for key in value if key != "design"}
    return value


def _item_types(inputs_schema: Any) -> dict[str, str | None]:
    return {entry.get("key"): entry.get("type") for entry in (inputs_schema or []) if isinstance(entry, dict)}


def _mappings(hog_function: HogFunction) -> list[dict[str, Any]]:
    return [mapping for mapping in (hog_function.mappings or []) if isinstance(mapping, dict)]


def _refresh_store(
    hog_function: HogFunction,
    store: dict[str, Any],
    item_types: dict[str, str | None],
    is_dwh_source: bool,
    mapping_index: int | None,
) -> Refresh:
    stamped = 0
    skipped = 0
    for key, item in store.items():
        if not isinstance(item, dict) or item.get("templating", "hog") != "hog" or "bytecode" not in item:
            continue
        try:
            bytecode = generate_template_bytecode(
                _compilable_value(item.get("value"), item_types.get(key)),
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
                mapping_index=mapping_index,
                input_key=key,
                error=str(e),
            )
            continue
        # The compiler returns opcode enums; the stored form is plain JSON, like a save writes it.
        item["bytecode"] = json.loads(json.dumps(bytecode))
        item["bytecode_contract"] = RUNTIME_CONTRACT
        stamped += 1
    return Refresh(stamped=stamped, skipped=skipped)


def refresh_input_templates(hog_function: HogFunction) -> Refresh:
    """
    Recompile every hog input template from its stored value, the way a save through the API does,
    and stamp it with the runtime it was checked against. The model's save only recompiles filters.
    This includes the inputs of each mapping, which the runtime merges into the invocation.

    An input the current guard refuses keeps its stored bytecode and gets no stamp: it fails at
    run time exactly as before, and an unstamped failure is classified as the owner's to fix.
    """
    is_dwh_source = (hog_function.filters or {}).get("source") in DATA_WAREHOUSE_SOURCES
    item_types = _item_types(hog_function.inputs_schema)
    results: list[Refresh] = []
    for store_name in ("inputs", "encrypted_inputs"):
        store: dict[str, Any] = getattr(hog_function, store_name) or {}
        result = _refresh_store(hog_function, store, item_types, is_dwh_source, mapping_index=None)
        if result.stamped:
            setattr(hog_function, store_name, store)
        results.append(result)
    for index, mapping in enumerate(_mappings(hog_function)):
        if isinstance(mapping.get("inputs"), dict):
            results.append(
                _refresh_store(
                    hog_function,
                    mapping["inputs"],
                    _item_types(mapping.get("inputs_schema")),
                    is_dwh_source,
                    mapping_index=index,
                )
            )
    return Refresh(stamped=sum(r.stamped for r in results), skipped=sum(r.skipped for r in results))


def refresh_mapping_filters(hog_function: HogFunction) -> Refresh:
    """
    Recompile the filters of each mapping, the way a save through the API does. The model's save only
    recompiles the top-level filters, and on a mapped destination the event filters live in the mappings.

    Filters that no longer compile keep their stored bytecode and get no stamp, the same as inputs.
    """
    stamped = 0
    skipped = 0
    for index, mapping in enumerate(_mappings(hog_function)):
        filters = mapping.get("filters")
        if not isinstance(filters, dict) or "bytecode" not in filters:
            continue
        # compile_filters_bytecode nulls the bytecode on error, so it gets a copy.
        compiled = compile_filters_bytecode({**filters}, hog_function.team)
        if compiled.get("bytecode_error"):
            skipped += 1
            logger.warning(
                "hog_function_mapping_filters_no_longer_compile",
                hog_function_id=str(hog_function.id),
                team_id=hog_function.team_id,
                mapping_index=index,
                error=compiled["bytecode_error"],
            )
            continue
        mapping["filters"] = compiled
        stamped += 1
    return Refresh(stamped=stamped, skipped=skipped)


def filters_compile(hog_function: HogFunction) -> bool:
    """Whether the top-level filters compile the way the model's save compiles them, without writing them."""
    return not compile_filters_bytecode({**(hog_function.filters or {})}, hog_function.team).get("bytecode_error")


class Command(BaseCommand):
    help = (
        "Refresh HogFunctions (both enabled and disabled) by re-saving them, which recompiles their "
        "filters, their hog input templates and their mappings, and stamps them with the current runtime contract"
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
        filters_stamped = 0
        filters_skipped = 0
        mapping_filters_stamped = 0
        mapping_filters_skipped = 0

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
                    refreshed_mapping_filters = refresh_mapping_filters(hog_function)
                    if dry_run:
                        compiled = filters_compile(hog_function)
                    else:
                        hog_function.save()
                        total_updated += 1
                        # The save leaves the error beside filters that no longer compile, and keeps their bytecode.
                        compiled = not (hog_function.filters or {}).get("bytecode_error")
                    # Counted after the save, so the summary reports what reached the database.
                    if compiled:
                        filters_stamped += 1
                    else:
                        filters_skipped += 1
                    inputs_stamped += refreshed.stamped
                    inputs_skipped += refreshed.skipped
                    mapping_filters_stamped += refreshed_mapping_filters.stamped
                    mapping_filters_skipped += refreshed_mapping_filters.skipped
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
                f"Filters stamped: {filters_stamped}, "
                f"Filters skipped: {filters_skipped}, "
                f"Inputs stamped: {inputs_stamped}, "
                f"Inputs skipped: {inputs_skipped}, "
                f"Mapping filters stamped: {mapping_filters_stamped}, "
                f"Mapping filters skipped: {mapping_filters_skipped}, "
                f"Errors: {error_count}"
            )
        )
