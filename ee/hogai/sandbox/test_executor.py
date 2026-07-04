from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.models import Task, TaskRun

from ee.hogai.sandbox.executor import handle_sandbox_message


class TestSandboxExecutor(APIBaseTest):
    def test_terminal_resume_carries_directory_snapshot_state(self) -> None:
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            agent_runtime=Conversation.AgentRuntime.SANDBOX,
        )
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )
        previous_run = task.create_run(mode="interactive")
        previous_run.status = TaskRun.Status.COMPLETED
        previous_run.state = {
            **(previous_run.state or {}),
            "snapshot_external_id": "snap-dir",
            "snapshot_kind": "directory",
            "snapshot_mount_path": "/tmp/workspace",
        }
        previous_run.save(update_fields=["status", "state"])

        response = object()
        with (
            patch("ee.hogai.sandbox.executor.get_sandbox_mapping") as get_sandbox_mapping,
            patch("ee.hogai.sandbox.executor.set_sandbox_mapping"),
            patch("ee.hogai.sandbox.executor._get_latest_stream_id", return_value="0"),
            patch("ee.hogai.sandbox.executor._seed_sandbox_stream"),
            patch("ee.hogai.sandbox.executor.execute_task_processing_workflow") as execute_workflow,
            patch("ee.hogai.sandbox.executor._make_streaming_response", return_value=response),
        ):
            get_sandbox_mapping.return_value = {
                "task_id": str(task.id),
                "run_id": str(previous_run.id),
            }

            result = handle_sandbox_message(
                conversation=conversation,
                conversation_id=str(conversation.id),
                content="resume please",
                user=self.user,
                team=self.team,
                is_new_conversation=False,
            )

        assert result is response
        new_run = task.runs.exclude(id=previous_run.id).get()
        assert new_run.state["resume_from_run_id"] == str(previous_run.id)
        assert new_run.state["pending_user_message"] == "resume please"
        assert new_run.state["snapshot_external_id"] == "snap-dir"
        assert new_run.state["snapshot_kind"] == "directory"
        assert new_run.state["snapshot_mount_path"] == "/tmp/workspace"

        conversation.refresh_from_db()
        assert conversation.sandbox_run_id == new_run.id
        execute_workflow.assert_called_once()
        assert execute_workflow.call_args.kwargs["run_id"] == str(new_run.id)
