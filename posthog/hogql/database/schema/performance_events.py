from posthog.hogql.database.models import (
    Table,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
)


class PerformanceEventsTable(Table):
    """HogQL table definition for network performance events stored in ClickHouse."""

    fields: dict[str, StringDatabaseField | DateTimeDatabaseField | IntegerDatabaseField | FloatDatabaseField] = {
        "uuid": StringDatabaseField(name="uuid"),
        "session_id": StringDatabaseField(name="session_id"),
        "window_id": StringDatabaseField(name="window_id"),
        "pageview_id": StringDatabaseField(name="pageview_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "timestamp": DateTimeDatabaseField(name="timestamp"),
        "time_origin": DateTimeDatabaseField(name="time_origin"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "entry_type": StringDatabaseField(name="entry_type"),
        "name": StringDatabaseField(name="name"),
        "current_url": StringDatabaseField(name="current_url"),
        "start_time": FloatDatabaseField(name="start_time"),
        "duration": FloatDatabaseField(name="duration"),
        "redirect_start": FloatDatabaseField(name="redirect_start"),
        "redirect_end": FloatDatabaseField(name="redirect_end"),
        "worker_start": FloatDatabaseField(name="worker_start"),
        "fetch_start": FloatDatabaseField(name="fetch_start"),
        "domain_lookup_start": FloatDatabaseField(name="domain_lookup_start"),
        "domain_lookup_end": FloatDatabaseField(name="domain_lookup_end"),
        "connect_start": FloatDatabaseField(name="connect_start"),
        "secure_connection_start": FloatDatabaseField(name="secure_connection_start"),
        "connect_end": FloatDatabaseField(name="connect_end"),
        "request_start": FloatDatabaseField(name="request_start"),
        "response_start": FloatDatabaseField(name="response_start"),
        "response_end": FloatDatabaseField(name="response_end"),
        "decoded_body_size": IntegerDatabaseField(name="decoded_body_size"),
        "encoded_body_size": IntegerDatabaseField(name="encoded_body_size"),
        "transfer_size": IntegerDatabaseField(name="transfer_size"),
        "initiator_type": StringDatabaseField(name="initiator_type"),
        "next_hop_protocol": StringDatabaseField(name="next_hop_protocol"),
        "render_blocking_status": StringDatabaseField(name="render_blocking_status"),
        "response_status": IntegerDatabaseField(name="response_status"),
        "dom_complete": FloatDatabaseField(name="dom_complete"),
        "dom_content_loaded_event": FloatDatabaseField(name="dom_content_loaded_event"),
        "dom_interactive": FloatDatabaseField(name="dom_interactive"),
        "load_event_end": FloatDatabaseField(name="load_event_end"),
        "load_event_start": FloatDatabaseField(name="load_event_start"),
        "redirect_count": IntegerDatabaseField(name="redirect_count"),
        "navigation_type": StringDatabaseField(name="navigation_type"),
        "unload_event_end": FloatDatabaseField(name="unload_event_end"),
        "unload_event_start": FloatDatabaseField(name="unload_event_start"),
        "largest_contentful_paint_element": StringDatabaseField(name="largest_contentful_paint_element"),
        "largest_contentful_paint_render_time": FloatDatabaseField(name="largest_contentful_paint_render_time"),
        "largest_contentful_paint_load_time": FloatDatabaseField(name="largest_contentful_paint_load_time"),
        "largest_contentful_paint_size": FloatDatabaseField(name="largest_contentful_paint_size"),
        "largest_contentful_paint_id": StringDatabaseField(name="largest_contentful_paint_id"),
        "largest_contentful_paint_url": StringDatabaseField(name="largest_contentful_paint_url"),
    }

    def to_printed_clickhouse_table_name(self) -> str:
        return "performance_events"

    def to_printed_hogql_table_name(self) -> str:
        return "performance_events"

    def get_asterisk(self) -> list[str]:
        return ["uuid", "session_id", "timestamp", "entry_type", "name", "response_status", "duration"]

    def clickhouse_table(self) -> str:
        return "performance_events"

    def hogql_table(self) -> str:
        return "performance_events"


