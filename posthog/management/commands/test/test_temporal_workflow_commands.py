import dataclasses

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command


@pytest.mark.parametrize(
    "command,client_method",
    [
        ("start_temporal_workflow", "start_workflow"),
        ("execute_temporal_workflow", "execute_workflow"),
    ],
)
@pytest.mark.parametrize(
    "workflow_name,inputs,expected_fields",
    [
        # dry_run defaults to True as a manual-run fail-safe, so an input-less CLI start is dry.
        ("data-catalog-weekly-digest", [], {"dry_run": True}),
        (
            "data-catalog-weekly-digest-test",
            ['{"email": "you@example.com"}'],
            {"email": "you@example.com"},
        ),
    ],
)
def test_commands_resolve_data_catalog_digest_workflows(command, client_method, workflow_name, inputs, expected_fields):
    mock_client = MagicMock()
    setattr(mock_client, client_method, AsyncMock(return_value={"ok": True}))

    with patch(f"posthog.management.commands.{command}.connect", new=AsyncMock(return_value=mock_client)):
        call_command(command, workflow_name, *inputs, "--workflow-id=test-workflow-id")

    call = getattr(mock_client, client_method).await_args
    assert call.args[0] == workflow_name
    assert expected_fields.items() <= dataclasses.asdict(call.args[1]).items()
