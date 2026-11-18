from typing import TYPE_CHECKING

from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.web_sessions_sql import DISTRIBUTED_WEB_SESSIONS_TABLE

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

_DIMENSIONS = {
    "channel_type": "Channel the session was attributed to, classified at write time.",
    "utm_source": "Entry utm_source.",
    "utm_medium": "Entry utm_medium.",
    "utm_campaign": "Entry utm_campaign.",
    "utm_term": "Entry utm_term.",
    "utm_content": "Entry utm_content.",
    "referring_domain": "Entry referring domain.",
    "entry_pathname": "Path of the session's first pageview.",
}


def _build_fields() -> dict[str, FieldOrTable]:
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the preaggregation job that produced this row."
        ),
        "period_bucket": DateTimeDatabaseField(
            name="period_bucket", description="Hourly UTC bucket on the session's start timestamp."
        ),
        "session_id_v7": IntegerDatabaseField(name="session_id_v7", description="The session this row describes."),
        "person_id": StringDatabaseField(
            name="person_id", description="Person ID when this row was computed; it can change after a merge."
        ),
        "start_timestamp": DateTimeDatabaseField(name="start_timestamp", description="When the session started (UTC)."),
        "min_event_timestamp": DateTimeDatabaseField(
            name="min_event_timestamp", description="Earliest event timestamp in the session (UTC)."
        ),
        "max_event_timestamp": DateTimeDatabaseField(
            name="max_event_timestamp", description="Latest event timestamp in the session (UTC)."
        ),
    }
    for name, description in _DIMENSIONS.items():
        fields[name] = StringDatabaseField(name=name, description=description)
    fields["pageview_count"] = IntegerDatabaseField(name="pageview_count", description="Pageviews in the session.")
    fields["computed_at"] = DateTimeDatabaseField(
        name="computed_at", description="When this row was computed; also the ReplacingMergeTree version."
    )
    fields["expires_at"] = DateTimeDatabaseField(
        name="expires_at", description="When this row expires and is dropped via TTL."
    )
    return fields


class WebSessionsPreaggregatedTable(Table):
    description: str = (
        "Internal preaggregated sessions (one row per session and stored person), carrying the "
        "session's entry attribution with the channel already classified. Feeds attribution in marketing analytics."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = _build_fields()

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return DISTRIBUTED_WEB_SESSIONS_TABLE()

    def to_printed_hogql(self) -> str:
        return "web_sessions_dimensional_preaggregated"
