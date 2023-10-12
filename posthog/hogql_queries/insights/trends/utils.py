from posthog.schema import ActionsNode, EventsNode


def series_event_name(series: EventsNode | ActionsNode) -> str | None:
    if isinstance(series, EventsNode):
        return series.event
    return None
