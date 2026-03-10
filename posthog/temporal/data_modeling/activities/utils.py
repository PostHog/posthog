import re
import datetime as dt

from products.data_modeling.backend.models import Node

# Regex patterns for stripping hostnames from ClickHouse error messages
# Matches patterns like: "(from chi-xxx.svc.cluster.local:9000)" or "(from 10.0.0.1:9000)"
_HOSTNAME_FROM_PATTERN = re.compile(r"\(from\s+[^\s\)]+:\d+\)")
# Matches patterns like: "Received from chi-xxx.svc.cluster.local:9000" or "Received from 10.0.0.1:9000"
_HOSTNAME_RECEIVED_PATTERN = re.compile(r"Received from\s+[^\s:]+:\d+")


def strip_hostname_from_error(error_message: str) -> str:
    """Strip hostname/IP information from error messages to avoid exposing internal infrastructure.

    This is used to sanitize error messages before showing them to users, while the original
    error message with the hostname should still be logged internally for debugging.

    Common patterns stripped:
    - "(from chi-xxx.svc.cluster.local:9000)" -> "(from [host])"
    - "Received from chi-xxx.svc.cluster.local:9000" -> "Received from [host]"
    """
    result = _HOSTNAME_FROM_PATTERN.sub("(from [host])", error_message)
    result = _HOSTNAME_RECEIVED_PATTERN.sub("Received from [host]", result)
    return result


def update_node_system_properties(
    node: Node,
    *,
    status: str,
    job_id: str,
    rows: int | None = None,
    duration_seconds: float | None = None,
    error: str | None = None,
) -> None:
    properties: dict = node.properties or {}
    system = properties.get("system", {})

    system["last_run_at"] = dt.datetime.now(dt.UTC).isoformat()
    system["last_run_status"] = status
    system["last_run_job_id"] = job_id
    if rows is not None:
        system["last_run_rows"] = rows
    if duration_seconds is not None:
        system["last_run_duration_seconds"] = duration_seconds
    if error is not None:
        system["last_run_error"] = error
    elif "last_run_error" in system:
        system["last_run_error"] = None

    properties["system"] = system
    node.properties = properties
