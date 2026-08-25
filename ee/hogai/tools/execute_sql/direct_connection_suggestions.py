"""Point a failed query at the live connection that actually holds the table it asked for.

A direct connection's tables are deliberately absent from the default catalog — they exist only when
the query names the connection. So an agent that writes ``SELECT * FROM orders`` against a connected
Postgres gets ``Unknown table `orders``` and no hint that the table is one parameter away. This turns
that dead end into the connection id to re-run with.
"""

import re
from functools import reduce
from operator import or_
from typing import TYPE_CHECKING, Optional

from django.db.models import Q

from posthog.hogql.direct_sql.capability import is_direct_capable

from posthog.ph_client import feature_enabled_or_false

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import DIRECT_ENGINE_BY_SOURCE_TYPE

if TYPE_CHECKING:
    from posthog.models import Team, User

# A missing-table hint is a nudge, not a catalog dump: past a handful of matches it stops helping and
# starts crowding out the error itself.
MAX_SUGGESTIONS = 5

# Table names come from the connected database and prefixes are user-set; a member who controls a
# shared connection could stuff newlines or a fake `</live_connection_suggestion>` close tag into
# either, and this hint lands verbatim in another member's agent context. These are identifiers, so
# they can't legitimately hold control characters or angle brackets — strip both and cap the length.
_UNSAFE_METADATA_RE = re.compile(r"[\x00-\x1f\x7f<>]")
MAX_METADATA_LENGTH = 200


def _sanitize_metadata(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", _UNSAFE_METADATA_RE.sub(" ", value)).strip()
    if len(collapsed) > MAX_METADATA_LENGTH:
        collapsed = collapsed[:MAX_METADATA_LENGTH].rstrip() + "…"
    return collapsed


def _live_queryable_sources(team: "Team", user: Optional["User"]) -> list[ExternalDataSource]:
    """Sources this user may live-query.

    Capability comes from the shared `is_direct_capable` predicate rather than being restated here, and
    the access check runs once against a single `UserAccessControl` — this is an error path, so it must
    not fan out into a query per source.
    """
    candidates = [
        source
        for source in ExternalDataSource.objects.filter(
            team_id=team.pk, source_type__in=list(DIRECT_ENGINE_BY_SOURCE_TYPE)
        )
        .exclude(deleted=True)
        .defer("job_inputs")
        if is_direct_capable(source)
    ]
    if not candidates or user is None:
        return candidates
    access_control = UserAccessControl(user=user, team=team)
    return [
        source for source in candidates if access_control.check_access_level_for_object(source, required_level="viewer")
    ]


def _name_filter(missing_tables: list[str], field: str) -> Q:
    """Match each missing name exactly, or as the last segment of a schema-qualified name.

    A connection commonly exposes `public.orders` while the query names `orders`. Both halves are
    case-insensitive because the engines these connections front fold identifier case differently.
    """
    return reduce(
        or_,
        (
            # nosemgrep: orm-field-injection -- field is a hardcoded caller literal ("name"), not user input; the user-supplied table names land only in the parameterized value position
            Q(**{f"{field}__iexact": name}) | Q(**{f"{field}__iendswith": f".{name}"})
            for name in missing_tables
        ),
    )


def _table_access_gate(team: "Team", user: Optional["User"]) -> Optional[UserAccessControl]:
    """A `UserAccessControl` to filter suggestions by table-level access, or None when none applies.

    Naming a connection's table in a hint confirms it exists, so it must honor the same per-table
    denials the HogQL catalog enforces (`Database._is_warehouse_table_denied`) — otherwise a member
    denied one table could probe for it with guessed names. Gating mirrors that catalog: only when
    the `hogql-warehouse-access-control` flag is on and there's a user to check against; org admins
    are unrestricted, so they skip filtering too.
    """
    if user is None:
        return None
    if not feature_enabled_or_false(
        "hogql-warehouse-access-control",
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    ):
        return None
    access_control = UserAccessControl(user=user, team=team)
    return None if access_control.is_organization_admin else access_control


def _matching_table_names(
    team: "Team", user: Optional["User"], sources: list[ExternalDataSource], missing_tables: list[str]
) -> dict[str, list[tuple[str, ExternalDataSource]]]:
    """Map each missing table (lowercased) to the `(table name, source)` pairs that could serve it."""
    wanted = {name.lower() for name in missing_tables}
    sources_by_id = {str(source.id): source for source in sources}
    found: dict[str, list[tuple[str, ExternalDataSource]]] = {}
    gate = _table_access_gate(team, user)

    def record(table_name: str, source_id: str) -> None:
        source = sources_by_id.get(source_id)
        if source is None:
            return
        lowered = table_name.lower()
        for candidate in (lowered, lowered.rsplit(".", 1)[-1]):
            if candidate in wanted:
                found.setdefault(candidate, []).append((table_name, source))
                return

    # Pure-direct sources expose warehouse table rows; dual-mode sources expose schema rows instead.
    pure_direct_ids = {
        source_id
        for source_id, source in sources_by_id.items()
        if source.access_method == ExternalDataSource.AccessMethod.DIRECT
    }
    dual_mode_ids = set(sources_by_id) - pure_direct_ids

    if pure_direct_ids:
        for table in DataWarehouseTable.objects.queryable().filter(
            _name_filter(missing_tables, "name"), team_id=team.pk, external_data_source_id__in=pure_direct_ids
        ):
            if gate is not None and not gate.check_access_level_for_object(table, required_level="viewer"):
                continue
            record(table.name, str(table.external_data_source_id))

    if dual_mode_ids:
        for schema in (
            ExternalDataSchema.objects.filter(
                _name_filter(missing_tables, "name"),
                team_id=team.pk,
                source_id__in=dual_mode_ids,
                should_sync=True,
            )
            .exclude(deleted=True)
            .select_related("table", "table__external_data_source")
        ):
            # A schema's access control lives on its synced table. Match the catalog's fail-closed
            # stance: a schema not yet backed by a table has nothing to authorize against, so deny it.
            if gate is not None and (
                schema.table is None or not gate.check_access_level_for_object(schema.table, required_level="viewer")
            ):
                continue
            record(schema.name, str(schema.source_id))

    return found


def build_direct_connection_suggestion(
    team: "Team", user: Optional["User"], missing_tables: list[str]
) -> Optional[str]:
    """A hint naming the connection each missing table lives on, or None if none of them do."""
    if not missing_tables:
        return None

    sources = _live_queryable_sources(team, user)
    if not sources:
        return None

    matches = _matching_table_names(team, user, sources, missing_tables)
    if not matches:
        return None

    lines = [
        "<live_connection_suggestion>",
        "These tables exist on a data warehouse connection, not in the default catalog. Re-run the "
        "query with the connection's id as connectionId — the query then reads that source live and "
        "may only reference its tables:",
    ]
    for requested in missing_tables:
        for table_name, source in matches.get(requested.lower(), [])[:MAX_SUGGESTIONS]:
            safe_prefix = _sanitize_metadata(source.prefix) if source.prefix else ""
            prefix = f", prefix '{safe_prefix}'" if safe_prefix else ""
            lines.append(
                f"- `{_sanitize_metadata(table_name)}` on connectionId {source.id} ({source.source_type}{prefix})"
            )
    lines.append(
        "List everything on a connection with `SELECT table_name FROM system.information_schema.tables` "
        "and that connectionId set."
    )
    lines.append("</live_connection_suggestion>")
    return "\n".join(lines)
