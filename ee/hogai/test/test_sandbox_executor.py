from unittest import mock

from django.test import override_settings

from ee.hogai.sandbox.executor import handle_sandbox_message


class TestSandboxKillswitch:
    @override_settings(DEBUG=False)
    def test_killswitch_answers_before_any_side_effect(self):
        # Everything past the killswitch launches work (conversation writes,
        # task runs, Temporal workflows). If the check drifts back after those,
        # a kill only discards the response while callers keep triggering the
        # work on every reconnect.
        conversation = mock.Mock()
        with (
            mock.patch("ee.hogai.sandbox.executor.has_sandbox_mode_feature_flag", return_value=True),
            mock.patch(
                "posthog.api.streaming.posthoganalytics.feature_enabled",
                side_effect=lambda flag, *args, **kwargs: flag == "sandbox-sse-killswitch",
            ),
            mock.patch("ee.hogai.sandbox.executor.get_sandbox_mapping") as get_mapping,
            mock.patch("ee.hogai.sandbox.executor.tasks_facade") as facade,
            mock.patch("ee.hogai.sandbox.executor.execute_task_processing_workflow") as workflow,
        ):
            response = handle_sandbox_message(
                conversation=conversation,
                conversation_id="cid",
                content="hello",
                user=mock.Mock(),
                team=mock.Mock(),
                is_new_conversation=True,
            )
        assert response.status_code == 204
        conversation.save.assert_not_called()
        get_mapping.assert_not_called()
        facade.create_run.assert_not_called()
        workflow.assert_not_called()
