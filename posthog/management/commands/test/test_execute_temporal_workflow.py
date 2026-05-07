import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command

from products.web_analytics.backend.temporal.weekly_digest.types import SendTestDigestInput, WAWeeklyDigestInput


@pytest.mark.django_db
@pytest.mark.parametrize(
    "workflow_name,inputs,expected_input_type",
    [
        ("wa-weekly-digest", [], WAWeeklyDigestInput),
        (
            "wa-weekly-digest-test",
            ['{"team_id": 1, "email": "you@example.com"}'],
            SendTestDigestInput,
        ),
    ],
)
def test_execute_temporal_workflow_supports_wa_digest_workflows(workflow_name, inputs, expected_input_type):
    mock_client = MagicMock()
    mock_client.execute_workflow = AsyncMock(return_value={"ok": True})

    with patch(
        "posthog.management.commands.execute_temporal_workflow.connect",
        new=AsyncMock(return_value=mock_client),
    ):
        call_command(
            "execute_temporal_workflow",
            workflow_name,
            *inputs,
            "--workflow-id=test-workflow-id",
        )

    assert mock_client.execute_workflow.await_count == 1
    execute_call = mock_client.execute_workflow.await_args
    assert execute_call.args[0] == workflow_name
    assert isinstance(execute_call.args[1], expected_input_type)
    if workflow_name == "wa-weekly-digest":
        assert execute_call.args[1] == WAWeeklyDigestInput(dry_run=False)
    if workflow_name == "wa-weekly-digest-test":
        assert execute_call.args[1] == SendTestDigestInput(team_id=1, email="you@example.com")
