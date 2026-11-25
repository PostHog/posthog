from datetime import datetime

from products.logs.backend.facade.internal_logs import InternalLogEntry, send_internal_logs


def send_internal_log(
    source: str, *, team_id: int, log_source_id: str, instance_id: str, timestamp: datetime, level: str, message: str
) -> None:
    """Does not wait for the network. Sends nothing unless the producer settings are set and allow the team."""
    send_internal_logs(
        source,
        [
            InternalLogEntry(
                team_id=team_id,
                log_source_id=log_source_id,
                instance_id=instance_id,
                timestamp=timestamp,
                level=level,
                message=message,
            )
        ],
    )
