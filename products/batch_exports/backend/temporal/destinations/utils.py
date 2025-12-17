import datetime as dt


def get_query_timeout(data_interval_start: dt.datetime | None, data_interval_end: dt.datetime) -> float:
    """Get the timeout to use for long running queries.

    Operations like COPY INTO TABLE and MERGE can take a long time to complete, especially if there is a lot of data and
    the instance being used is not very powerful. We don't want to allow these queries to run for too long, as they can
    cause SLA violations and can consume a lot of resources in the user's instance.
    """
    min_timeout_seconds = 20 * 60  # 20 minutes
    max_timeout_seconds = 6 * 60 * 60  # 6 hours

    if data_interval_start is None:
        return max_timeout_seconds

    interval_seconds = (data_interval_end - data_interval_start).total_seconds()
    # We don't want the timeout to be too short (eg in case of 5 min batch exports)
    timeout_seconds = max(min_timeout_seconds, interval_seconds * 0.8)
    # We don't want the timeout to be too long (eg in case of 1 day batch exports)
    return min(timeout_seconds, max_timeout_seconds)
