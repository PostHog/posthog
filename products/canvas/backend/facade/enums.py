"""Exported enums for canvas."""

from django.db import models


class ConnectorCallStatus(models.TextChoices):
    OK = "ok"
    NOT_CONNECTED = "not_connected"
    NEEDS_REAUTH = "needs_reauth"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"
    TOOL_MISSING = "tool_missing"
    WRITE_BLOCKED = "write_blocked"
    UPSTREAM_ERROR = "upstream_error"


class ConnectorKind(models.TextChoices):
    NATIVE = "native"
    MCP = "mcp"
