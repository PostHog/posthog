from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.comment import Comment
from posthog.models.comment.utils import build_comment_item_url, extract_plain_text_from_rich_content
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.redis import get_client
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV, POSTHOG_AI_APP_CLIENT_ID_DEV

from products.access_control.backend.models.access_control import AccessControl
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.reply_dedupe import REPLY_IN_PROGRESS_ERROR_TYPE, ReplyFingerprint, reserve


class TestComments(APIBaseTest, QueryMatchingTest):
    def _sandbox_task_comment_client(
        self, task_id=None, *, client_id=ARRAY_APP_CLIENT_ID_DEV, scopes="task:read comment:read"
    ):
        app = OAuthApplication.objects.create(
            name="Task comments sandbox",
            client_id=client_id,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token="pha_task_comments",
            scope=scopes,
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return self.client

    def _task_artifact_target(self, *, public: bool = True, creator=None):
        task_channel_model = apps.get_model("tasks", "Channel")
        task_model = apps.get_model("tasks", "Task")
        task_run_model = apps.get_model("tasks", "TaskRun")
        channel = None
        if public:
            channel, _ = task_channel_model.objects.unscoped().get_or_create(
                team=self.team,
                name="comment-test",
                defaults={"created_by": self.user},
            )
        task = task_model.objects.create(
            team=self.team,
            title="Comment target",
            created_by=creator or self.user,
            channel=channel,
        )
        task_run_model.objects.create(
            team=self.team,
            task=task,
            artifacts=[{"id": "artifact-1", "name": "report.md", "type": "output"}],
        )
        return task

    def test_task_artifact_comments_require_a_visible_owning_task(self) -> None:
        task = self._task_artifact_target()
        payload: dict[str, Any] = {
            "content": "Review this",
            "scope": "task_artifact",
            "item_id": "artifact-1",
            "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
        }

        created = self.client.post(f"/api/projects/{self.team.id}/comments", payload)
        assert created.status_code == status.HTTP_201_CREATED
        without_task = self.client.get(f"/api/projects/{self.team.id}/comments?scope=task_artifact&item_id=artifact-1")
        assert without_task.json()["results"] == []
        unscoped = self.client.get(f"/api/projects/{self.team.id}/comments?item_id=artifact-1")
        assert unscoped.json()["results"] == []
        with_task = self.client.get(
            f"/api/projects/{self.team.id}/comments?scope=task_artifact&item_id=artifact-1&task_id={task.id}"
        )
        assert [row["id"] for row in with_task.json()["results"]] == [created.json()["id"]]

    @mock.patch("posthog.api.comments.send_mention_notifications")
    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_desktop_comment_mentions_do_not_enqueue_email(
        self,
        send_email: mock.Mock,
        produce_events: mock.Mock,
        send_notifications: mock.Mock,
    ) -> None:
        task = self._task_artifact_target()
        mentioned = User.objects.create_and_join(self.organization, "desktop-mentioned@example.com", None)
        payload = {
            "content": "Review this",
            "scope": "task_artifact",
            "item_id": "artifact-1",
            "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
            "mentions": [mentioned.id],
        }

        created = self.client.post(f"/api/projects/{self.team.id}/comments", payload)
        updated = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{created.json()['id']}",
            {"content": "Review this update", "mentions": [mentioned.id]},
        )

        assert created.status_code == status.HTTP_201_CREATED
        assert updated.status_code == status.HTTP_200_OK
        send_email.assert_not_called()
        assert produce_events.call_count == 2
        assert send_notifications.call_count == 2

    @mock.patch("posthog.api.comments.posthoganalytics.capture")
    def test_task_comment_actions_track_mentions_without_counting_state_as_replies(self, capture: mock.Mock) -> None:
        task = self._task_artifact_target()
        mentioned = User.objects.create_and_join(self.organization, "comment-mention@example.com", None)
        item_context = {
            "anchor": {"kind": "unsupported"},
            "taskId": str(task.id),
        }
        target = {
            "scope": "task_artifact",
            "item_id": "artifact-1",
            "item_context": item_context,
        }

        root = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                **target,
                "content": "A" * 60,
                "mentions": [mentioned.id],
                "item_context": {**item_context, "threadState": "resolved"},
            },
        )
        reply = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {**target, "content": "Reply", "source_comment": root.json()["id"]},
        )
        resolved = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                **target,
                "content": "Resolved this thread",
                "source_comment": root.json()["id"],
                "item_context": {**item_context, "threadState": "resolved"},
            },
        )

        assert root.status_code == status.HTTP_201_CREATED
        assert reply.status_code == status.HTTP_201_CREATED
        assert resolved.status_code == status.HTTP_201_CREATED
        events = [call.kwargs for call in capture.call_args_list if call.kwargs.get("event") == "Comment action"]
        assert [event["properties"]["action_type"] for event in events] == ["created", "replied", "resolved"]
        assert events[0]["properties"] == {
            "analytics_version": 1,
            "action_type": "created",
            "scope": "task_artifact",
            "anchor_kind": "unknown",
            "task_id": str(task.id),
            "item_id": "artifact-1",
            "thread_id": root.json()["id"],
            "comment_id": root.json()["id"],
            "is_reply": False,
            "mention_count": 1,
            "content_length_bucket": "51-200",
            "thread_state": "open",
        }
        assert events[1]["properties"]["is_reply"] is True
        assert events[1]["properties"]["mention_count"] == 0
        assert events[2]["properties"]["is_reply"] is False
        assert events[2]["properties"]["thread_state"] == "resolved"
        assert all(event["event"] == "Comment action" for event in events)

        capture.reset_mock()
        notebook = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"scope": "Notebook", "content": "Not a task comment"},
        )
        assert notebook.status_code == status.HTTP_201_CREATED
        assert not any(call.kwargs.get("event") == "Comment action" for call in capture.call_args_list)

        capture.side_effect = RuntimeError("Analytics unavailable")
        saved = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {**target, "content": "Still saved"},
        )
        assert saved.status_code == status.HTTP_201_CREATED

    def test_task_comments_list_artifacts_comments_and_one_comment(self) -> None:
        task = self._task_artifact_target()
        task_run_model = apps.get_model("tasks", "TaskRun")
        task_run_model.objects.create(
            team=self.team,
            task=task,
            artifacts=[{"id": "artifact-1", "name": "latest-report.md", "type": "output"}],
        )
        canvas_id = "019fcbe9-839f-7571-ad42-31aa5f615112"
        apps.get_model("tasks", "TaskThreadMessage").objects.for_team(self.team.id).create(
            team=self.team,
            task=task,
            event="canvas_created",
            content="Canvas created",
            payload={
                "canvas_name": "Research canvas",
                "canvas_url": f"https://app.posthog.com/code/canvas/channel/{canvas_id}",
            },
        )
        root = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task_artifact",
            item_id="artifact-1",
            item_context={
                "taskId": str(task.id),
                "anchor": {"kind": "text", "quote": "important output", "start": 0, "end": 16},
                "canvasVersionId": "version-2",
            },
            content="Please tighten this section",
        )
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task_artifact",
            item_id="artifact-1",
            item_context={"taskId": str(task.id), "anchor": {"kind": "document"}},
            source_comment=root,
            content="Done",
        )
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task_artifact",
            item_id="artifact-1",
            item_context={"taskId": str(task.id), "threadState": "unexpected"},
            source_comment=root,
            content="Malformed state is still a reply",
        )
        client = self._sandbox_task_comment_client(task.id)

        artifacts = client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/artifacts/")
        assert artifacts.status_code == status.HTTP_200_OK
        assert artifacts.json() == {
            "artifacts": [
                {
                    "id": "artifact-1",
                    "type": "artifact",
                    "name": "latest-report.md",
                },
                {"id": canvas_id, "type": "canvas", "name": "Research canvas"},
            ]
        }

        comments = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/comments/?artifact_id=artifact-1",
        )
        assert comments.status_code == status.HTTP_200_OK
        assert comments.json()["comments"] == [
            {
                "id": str(root.id),
                "target": {"id": "artifact-1", "type": "artifact", "name": "latest-report.md"},
                "content": "Please tighten this section",
                "content_truncated": False,
                "selected_text": "important output",
                "created_at": root.created_at.isoformat().replace("+00:00", "Z"),
                "reply_count": 2,
                "resolved": False,
            }
        ]

        detail = client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/comments/{root.id}/")
        assert detail.status_code == status.HTTP_200_OK
        assert [comment["content"] for comment in detail.json()["comments"]] == [
            "Please tighten this section",
            "Done",
            "Malformed state is still a reply",
        ]
        assert all(not comment["content_truncated"] for comment in detail.json()["comments"])
        assert all(comment["content_next_offset"] is None for comment in detail.json()["comments"])
        assert detail.json()["comments"][0]["anchor"] == {
            "end": 16,
            "kind": "text",
            "quote": "important output",
            "start": 0,
        }
        assert detail.json()["comments"][0]["canvas_version_id"] == "version-2"
        assert detail.json()["next"] is None

    def test_task_comment_retrieval_tolerates_malformed_stored_context(self) -> None:
        task = self._task_artifact_target()
        root = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task",
            item_id=str(task.id),
            item_context=[],
            content="Legacy malformed context",
        )
        client = self._sandbox_task_comment_client(task.id)

        response = client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/comments/{root.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["comments"][0]["anchor"] is None

    def test_task_comment_bodies_are_byte_bounded_and_continuable(self) -> None:
        task = self._task_artifact_target()
        root = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task_artifact",
            item_id="artifact-1",
            item_context={"taskId": str(task.id), "anchor": {"kind": "document"}},
            content="é" * 40_000,
        )
        client = self._sandbox_task_comment_client(task.id)

        listed = client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/comments/").json()["comments"][0]
        assert len(listed["content"].encode("utf-8")) <= 1024
        assert listed["content_truncated"] is True

        detail = client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/comments/{root.id}/").json()
        first_chunk = detail["comments"][0]
        assert len(first_chunk["content"].encode("utf-8")) <= 64 * 1024
        assert first_chunk["content_truncated"] is True
        assert first_chunk["content_next_offset"] is not None

        continuation = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/comments/{root.id}/",
            {"comment_id": str(root.id), "content_offset": first_chunk["content_next_offset"]},
        ).json()["comments"][0]
        assert continuation["content"]
        assert continuation["content_truncated"] is False
        assert continuation["content_next_offset"] is None

    def test_task_comments_use_an_opaque_cursor(self) -> None:
        task = self._task_artifact_target()
        for content in ("First", "Second"):
            Comment.objects.create(
                team=self.team,
                created_by=self.user,
                scope="task",
                item_id=str(task.id),
                content=content,
            )
        client = self._sandbox_task_comment_client(task.id)

        first = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/comments/?limit=1",
        ).json()
        second = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/comments/?limit=1&cursor={first['next']}",
        ).json()

        assert [row["content"] for row in first["comments"]] == ["Second"]
        assert [row["content"] for row in second["comments"]] == ["First"]
        assert second["next"] is None

    def test_task_comments_scan_past_resolved_roots(self) -> None:
        task = self._task_artifact_target()
        roots = []
        for content in ("Open older", "Resolved newer"):
            roots.append(
                Comment.objects.create(
                    team=self.team,
                    created_by=self.user,
                    scope="task",
                    item_id=str(task.id),
                    content=content,
                )
            )
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task",
            item_id=str(task.id),
            source_comment=roots[1],
            item_context={"threadState": "resolved"},
            content="resolved",
        )
        client = self._sandbox_task_comment_client(task.id)

        response = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/comments/?limit=1",
        ).json()

        assert [row["content"] for row in response["comments"]] == ["Open older"]

    def test_task_comment_replies_are_paginated(self) -> None:
        task = self._task_artifact_target()
        root = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task",
            item_id=str(task.id),
            content="Root",
        )
        Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task",
            item_id=str(task.id),
            source_comment=root,
            content="Reply",
        )
        client = self._sandbox_task_comment_client(task.id)

        first = client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/comments/{root.id}/?limit=1").json()
        second = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/comments/{root.id}/?limit=1&cursor={first['next']}",
        ).json()

        assert [row["content"] for row in first["comments"]] == ["Root"]
        assert [row["content"] for row in second["comments"]] == ["Reply"]
        assert second["next"] is None

    def test_task_comments_cannot_read_another_task_comment(self) -> None:
        current_task = self._task_artifact_target()
        other_task = self._task_artifact_target()
        other_comment = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="task",
            item_id=str(other_task.id),
            item_context={"anchor": {"kind": "document"}},
            content="Other task comment",
        )
        client = self._sandbox_task_comment_client(current_task.id)

        response = client.get(
            f"/api/projects/{self.team.id}/tasks/{current_task.id}/comments/{other_comment.id}/",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_task_comments_require_the_sandbox_task_binding(self) -> None:
        task = self._task_artifact_target()

        response = self.client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/artifacts/",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_task_comments_ask_legacy_sandboxes_to_restart(self) -> None:
        task = self._task_artifact_target()
        client = self._sandbox_task_comment_client()

        response = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/artifacts/",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "Restart the task" in str(response.json())

    def test_task_comments_reject_an_alternate_task_url_for_the_same_user(self) -> None:
        bound_task = self._task_artifact_target()
        other_task = self._task_artifact_target()
        client = self._sandbox_task_comment_client(bound_task.id)

        response = client.get(
            f"/api/projects/{self.team.id}/tasks/{other_task.id}/artifacts/",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_task_comments_reject_a_posthog_ai_sandbox_token(self) -> None:
        task = self._task_artifact_target()
        client = self._sandbox_task_comment_client(task.id, client_id=POSTHOG_AI_APP_CLIENT_ID_DEV)

        response = client.get(
            f"/api/projects/{self.team.id}/tasks/{task.id}/artifacts/",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_task_comments_require_comment_read_scope(self) -> None:
        task = self._task_artifact_target()
        client = self._sandbox_task_comment_client(task.id, scopes="task:read")

        response = client.get(f"/api/projects/{self.team.id}/tasks/{task.id}/comments/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_task_artifact_comments_reject_mismatched_and_private_targets(self) -> None:
        other = User.objects.create_and_join(self.organization, "private-task-owner@posthog.com", "password")
        task = self._task_artifact_target(public=False, creator=other)
        payload: dict[str, Any] = {
            "content": "Should not land",
            "scope": "task_artifact",
            "item_id": "artifact-1",
            "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
        }
        assert self.client.post(f"/api/projects/{self.team.id}/comments", payload).status_code == 403

        visible_task = self._task_artifact_target()
        payload["item_context"]["taskId"] = str(visible_task.id)
        payload["item_id"] = "not-on-visible-task"
        assert self.client.post(f"/api/projects/{self.team.id}/comments", payload).status_code == 403

    def test_private_task_comment_thread_is_invisible_to_other_users(self) -> None:
        other = User.objects.create_and_join(self.organization, "private-thread-owner@posthog.com", "password")
        task = self._task_artifact_target(public=False, creator=other)
        root = Comment.objects.create(
            team=self.team,
            created_by=other,
            scope="task",
            item_id=str(task.id),
            content="Private root",
        )
        Comment.objects.create(
            team=self.team,
            created_by=other,
            scope="task",
            item_id=str(task.id),
            source_comment=root,
            content="Private reply",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/comments/{root.id}/thread")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_canvas_comments_use_the_relational_canvas_owner(self) -> None:
        task = self._task_artifact_target()
        channel = task.channel
        canvas_model = apps.get_model("canvas", "Canvas")
        canvas = canvas_model.objects.unscoped().create(
            team=self.team,
            channel=channel,
            name="Launch canvas",
            created_by=self.user,
        )
        canvas_version_model = apps.get_model("canvas", "CanvasSourceVersion")
        canvas_version_model.objects.unscoped().create(
            team=self.team,
            canvas=canvas,
            source_hash="a" * 64,
            source_object_key="canvases/test/source.json",
            source_size=2,
            task_id=task.id,
            created_by=self.user,
        )
        mentioned = User.objects.create_and_join(self.organization, "canvas-mentioned@posthog.com", "password")
        payload: dict[str, Any] = {
            "content": "Review this canvas",
            "scope": "desktop_canvas",
            "item_id": str(canvas.id),
            "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
            "mentions": [mentioned.id],
        }

        created = self.client.post(f"/api/projects/{self.team.id}/comments", payload)

        assert created.status_code == status.HTTP_201_CREATED
        with_task = self.client.get(
            f"/api/projects/{self.team.id}/comments?scope=desktop_canvas&item_id={canvas.id}&task_id={task.id}"
        )
        assert [row["id"] for row in with_task.json()["results"]] == [created.json()["id"]]
        task_activity_model = apps.get_model("tasks", "TaskCommentActivity")
        assert (
            task_activity_model.objects.unscoped()
            .filter(
                team=self.team,
                user=mentioned,
                task=task,
                comment_id=created.json()["id"],
            )
            .exists()
        )

        other_task = self._task_artifact_target()
        payload["item_context"]["taskId"] = str(other_task.id)
        assert self.client.post(f"/api/projects/{self.team.id}/comments", payload).status_code == 403

    def test_canvas_comments_respect_personal_channel_visibility(self) -> None:
        task = self._task_artifact_target()
        other = User.objects.create_and_join(self.organization, "private-canvas-owner@posthog.com", "password")
        channel_model = apps.get_model("tasks", "Channel")
        channel = channel_model.objects.unscoped().create(
            team=self.team,
            name="private-canvas",
            channel_type="personal",
            created_by=other,
        )
        canvas_model = apps.get_model("canvas", "Canvas")
        canvas = canvas_model.objects.unscoped().create(
            team=self.team,
            channel=channel,
            name="Private canvas",
            created_by=other,
            generation_task_id=task.id,
        )
        payload = {
            "content": "Should not land",
            "scope": "desktop_canvas",
            "item_id": str(canvas.id),
            "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
        }

        assert self.client.post(f"/api/projects/{self.team.id}/comments", payload).status_code == 403
        response = self.client.get(
            f"/api/projects/{self.team.id}/comments?scope=desktop_canvas&item_id={canvas.id}&task_id={task.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_comment_without_a_mention_notifies_the_task_owner(self) -> None:
        task = self._task_artifact_target()
        owner = User.objects.create_and_join(self.organization, "owner@posthog.com", "password")
        task.created_by = owner
        task.save(update_fields=["created_by"])

        created = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Review when ready",
                "scope": "task_artifact",
                "item_id": "artifact-1",
                "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
            },
        )

        assert created.status_code == status.HTTP_201_CREATED
        activity_model = apps.get_model("tasks", "TaskCommentActivity")
        activity = activity_model.objects.unscoped().get(team=self.team, user=owner, comment_id=created.json()["id"])
        assert activity.kind == "owned_item_comment"

    @mock.patch("products.tasks.backend.tasks.tasks.project_task_comment_activity.delay")
    @mock.patch("products.tasks.backend.facade.api.record_comment_activity", side_effect=RuntimeError("activity down"))
    def test_activity_projection_failure_schedules_recovery(
        self,
        _record_activity: mock.Mock,
        retry_projection: mock.Mock,
    ) -> None:
        task = self._task_artifact_target()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/comments",
                {
                    "content": "Still persist this",
                    "scope": "task_artifact",
                    "item_id": "artifact-1",
                    "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
                },
            )

        assert response.status_code == status.HTTP_201_CREATED
        assert Comment.objects.filter(id=response.json()["id"], team=self.team).exists()
        retry_projection.assert_called_once_with(
            team_id=self.team.id,
            comment_id=response.json()["id"],
            mentioned_user_ids=[],
            include_relationship_recipients=True,
            target_owner_id=None,
            activity_at=None,
        )

    def test_reply_inherits_its_root_comment_target(self) -> None:
        task = self._task_artifact_target()
        root = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Root",
                "scope": "task_artifact",
                "item_id": "artifact-1",
                "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
            },
        ).json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Reply",
                "scope": "Insight",
                "item_id": "another-resource",
                "item_context": {"taskId": "00000000-0000-4000-8000-000000000000", "is_emoji": True},
                "source_comment": root["id"],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["source_comment"] == root["id"]
        assert response.json()["scope"] == "task_artifact"
        assert response.json()["item_id"] == "artifact-1"
        assert response.json()["item_context"] == {
            "anchor": {"kind": "document"},
            "taskId": str(task.id),
            "is_emoji": True,
        }

    @parameterized.expand(
        [
            ("resolved", True),
            ("open", True),
            ("unexpected", False),
        ]
    )
    def test_reply_thread_state_survives_root_context_merge(self, thread_state: str, kept: bool) -> None:
        task = self._task_artifact_target()
        root = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Root",
                "scope": "task_artifact",
                "item_id": "artifact-1",
                "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
            },
        ).json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Resolved this thread",
                "item_context": {"threadState": thread_state},
                "source_comment": root["id"],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        item_context = response.json()["item_context"]
        if kept:
            assert item_context["threadState"] == thread_state
        else:
            assert "threadState" not in item_context

    @mock.patch("posthog.api.comments.send_mention_notifications")
    def test_personal_channel_comments_ignore_mentions(self, send_notifications: mock.Mock) -> None:
        task = self._task_artifact_target()
        task.channel.channel_type = "personal"
        task.channel.save(update_fields=["channel_type"])
        mentioned = User.objects.create_and_join(self.organization, "private-mentioned@posthog.com", "password")

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This stays private @[Mentioned](private-mentioned@posthog.com)",
                "scope": "task_artifact",
                "item_id": "artifact-1",
                "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
                "mentions": [mentioned.id],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        send_notifications.assert_not_called()
        task_activity_model = apps.get_model("tasks", "TaskCommentActivity")
        assert not task_activity_model.objects.unscoped().filter(team=self.team, user=mentioned, task=task).exists()

    @mock.patch("posthog.api.comments._record_task_comment_activity")
    def test_edit_mentions_do_not_repeat_relationship_notifications(self, record_activity: mock.Mock) -> None:
        task = self._task_artifact_target()
        mentioned = User.objects.create_and_join(self.organization, "mentioned@posthog.com", "password")
        created = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Old comment",
                "scope": "task_artifact",
                "item_id": "artifact-1",
                "item_context": {"anchor": {"kind": "document"}, "taskId": str(task.id)},
            },
        )
        assert created.status_code == status.HTTP_201_CREATED
        record_activity.reset_mock()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{created.json()['id']}"
            f"?scope=task_artifact&item_id=artifact-1&task_id={task.id}",
            {"content": "Edited mention", "mentions": [mentioned.id]},
        )

        assert response.status_code == status.HTTP_200_OK
        assert record_activity.call_args.kwargs["include_relationship_recipients"] is False
        assert record_activity.call_args.kwargs["activity_at"] is not None

    def _create_comment(self, data: dict | None = None) -> Any:
        if data is None:
            data = {}
        payload = {
            "content": "my content",
            "scope": "Notebook",
        }

        payload.update(data)

        return self.client.post(
            f"/api/projects/{self.team.id}/comments",
            payload,
        ).json()

    def test_creates_comment_with_validation_errors(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This is a comment",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": "scope",
        }

    def test_rejects_non_object_comment_context(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "This is a comment", "scope": "Notebook", "item_context": []},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "item_context"

    def test_creates_comment_successfully(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This is a comment",
                "scope": "Notebook",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json() == {
            "id": mock.ANY,
            "created_by": response.json()["created_by"],
            "content": "This is a comment",
            "rich_content": None,
            "deleted": False,
            "version": 0,
            "created_at": mock.ANY,
            "item_id": None,
            "item_context": None,
            "scope": "Notebook",
            "source_comment": None,
            "is_task": False,
            "completed_at": None,
            "completed_by": None,
            "slack_thread": None,
        }

    def test_updates_content_and_increments_version(self) -> None:
        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "This is a comment", "scope": "Notebook"},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {
                "content": "This is an edited comment",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "id": mock.ANY,
            "created_by": response.json()["created_by"],
            "content": "This is an edited comment",
            "rich_content": None,
            "deleted": False,
            "version": 1,
            "created_at": mock.ANY,
            "item_id": None,
            "item_context": None,
            "scope": "Notebook",
            "source_comment": None,
            "is_task": False,
            "completed_at": None,
            "completed_by": None,
            "slack_thread": None,
        }

    def test_empty_comments_list(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "next": None,
            "previous": None,
            "results": [],
        }

    def test_lists_comments(self) -> None:
        self._create_comment({"content": "comment 1"})
        self._create_comment({"content": "comment 2"})
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert len(response.json()["results"]) == 2

        assert response.json()["results"][0]["content"] == "comment 2"
        assert response.json()["results"][1]["content"] == "comment 1"

    def test_lists_comments_filtering(self) -> None:
        self._create_comment({"content": "comment notebook-1", "scope": "Notebook", "item_id": "1"})
        self._create_comment({"content": "comment notebook-2", "scope": "Notebook", "item_id": "2"})
        self._create_comment({"content": "comment dashboard-1", "scope": "Dashboard", "item_id": "1"})

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=Notebook")
        assert len(response.json()["results"]) == 2
        assert response.json()["results"][0]["content"] == "comment notebook-2"
        assert response.json()["results"][1]["content"] == "comment notebook-1"

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=Notebook&item_id=2")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["content"] == "comment notebook-2"

    def test_lists_comments_thread(self) -> None:
        initial_comment = self._create_comment({"content": "comment notebook-1", "scope": "Notebook", "item_id": "1"})
        self._create_comment({"content": "comment reply", "source_comment": initial_comment["id"]})
        self._create_comment({"content": "comment other reply", "source_comment": initial_comment["id"]})
        self._create_comment({"content": "comment elsewhere"})

        for url in [
            f"/api/projects/{self.team.id}/comments/{initial_comment['id']}/thread",
            f"/api/projects/{self.team.id}/comments/?source_comment={initial_comment['id']}",
        ]:
            response = self.client.get(url)
            assert len(response.json()["results"]) == 2
            assert response.json()["results"][0]["content"] == "comment other reply"
            assert response.json()["results"][1]["content"] == "comment reply"

    @parameterized.expand(
        [
            ("no_comments", [], "", 0),
            (
                "two_comments_different_scopes",
                [
                    {"content": "comment 1", "scope": "Notebook", "item_id": "1"},
                    {"content": "comment 2", "scope": "Dashboard", "item_id": "2"},
                ],
                "",
                2,
            ),
            (
                "filter_by_scope",
                [
                    {"content": "comment 1", "scope": "Notebook", "item_id": "1"},
                    {"content": "comment 2", "scope": "Dashboard", "item_id": "2"},
                ],
                "?scope=Notebook",
                1,
            ),
        ]
    )
    def test_count_comments(self, name: str, comments_to_create: list, query_params: str, expected_count: int) -> None:
        for comment_data in comments_to_create:
            self._create_comment(comment_data)

        response = self.client.get(f"/api/projects/{self.team.id}/comments/count{query_params}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"count": expected_count}

    @parameterized.expand(
        [
            (
                "excludes_only_the_2_emoji_reactions",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "another comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {"content": "❤️", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {
                        "content": "comment with context",
                        "scope": "Notebook",
                        "item_id": "1",
                        "item_context": {"other_field": "value"},
                    },
                ],
                "?exclude_emoji_reactions=true",
                3,
            ),
            (
                "counts_all_comments_including_emojis",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "another comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {"content": "❤️", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {
                        "content": "comment with context",
                        "scope": "Notebook",
                        "item_id": "1",
                        "item_context": {"other_field": "value"},
                    },
                ],
                "",
                5,
            ),
            (
                "only_notebook_comments_excluding_emoji_reactions",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "another comment", "scope": "Notebook", "item_id": "1"},
                    {"content": "dashboard comment", "scope": "Dashboard", "item_id": "2"},
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                    {"content": "❤️", "scope": "Dashboard", "item_id": "2", "item_context": {"is_emoji": True}},
                ],
                "?scope=Notebook&exclude_emoji_reactions=true",
                2,
            ),
            (
                "includes_comments_with_is_emoji_false",
                [
                    {"content": "regular comment", "scope": "Notebook", "item_id": "1"},
                    {
                        "content": "explicitly not emoji",
                        "scope": "Notebook",
                        "item_id": "1",
                        "item_context": {"is_emoji": False},
                    },
                    {"content": "👍", "scope": "Notebook", "item_id": "1", "item_context": {"is_emoji": True}},
                ],
                "?exclude_emoji_reactions=true",
                2,
            ),
        ]
    )
    def test_count_comments_with_emoji_filtering(
        self, name: str, comments_to_create: list, query_params: str, expected_count: int
    ) -> None:
        for comment_data in comments_to_create:
            self._create_comment(comment_data)

        response = self.client.get(f"/api/projects/{self.team.id}/comments/count{query_params}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"count": expected_count}

    def test_creates_llm_trace_comment_successfully(self) -> None:
        trace_id = "test-trace-123"
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "This trace has high latency",
                "scope": "LLMTrace",
                "item_id": trace_id,
                "item_context": {"trace_id": trace_id},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json()["scope"] == "LLMTrace"
        assert response.json()["item_id"] == trace_id
        assert response.json()["content"] == "This trace has high latency"

    def test_filters_llm_trace_comments(self) -> None:
        trace_id_1 = "trace-1"
        trace_id_2 = "trace-2"

        self._create_comment({"content": "Trace 1 comment", "scope": "LLMTrace", "item_id": trace_id_1})
        self._create_comment({"content": "Trace 2 comment", "scope": "LLMTrace", "item_id": trace_id_2})

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=LLMTrace")
        assert len(response.json()["results"]) == 2

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope=LLMTrace&item_id={trace_id_1}")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["content"] == "Trace 1 comment"

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_extracts_mentions_from_rich_content_on_create(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "mentioned@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Hey "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                                {"type": "text", "text": " check this out"},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert call_args[0][1] == [mentioned_user.id]

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_extracts_mentions_from_rich_content_on_update(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "mentioned_update@posthog.com", None)

        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "Original comment", "scope": "Notebook"},
        )

        mock_send_email.reset_mock()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {
                "content": "",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Edited to mention "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert call_args[0][1] == [mentioned_user.id]

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_uses_explicit_mentions_field_when_provided(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user_1 = User.objects.create_and_join(self.organization, "explicit_user1@posthog.com", None)
        mentioned_user_2 = User.objects.create_and_join(self.organization, "explicit_user2@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "mentions": [mentioned_user_1.id, mentioned_user_2.id],
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Test"}],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert set(call_args[0][1]) == {mentioned_user_1.id, mentioned_user_2.id}

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_deduplicates_mentions_from_rich_content(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "duplicate@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Hey "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                                {"type": "text", "text": " and "},
                                {"type": "ph-mention", "attrs": {"id": mentioned_user.id}},
                                {"type": "text", "text": " again"},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert call_args[0][1] == [mentioned_user.id]
        assert len(call_args[0][1]) == 1

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_ignores_non_integer_ids_in_rich_content(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
        from posthog.models import User

        valid_user = User.objects.create_and_join(self.organization, "valid@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Notebook",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "ph-mention", "attrs": {"id": "invalid_string"}},
                                {"type": "ph-mention", "attrs": {"id": valid_user.id}},
                                {"type": "ph-mention", "attrs": {"id": None}},
                                {"type": "ph-mention", "attrs": {"id": 999.5}},
                            ],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        assert call_args[0][1] == [valid_user.id]

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_passes_slug_parameter_when_provided(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "slug_test@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Replay",
                "item_id": "test-replay-id",
                "slug": "/replay/test-replay-id",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "ph-mention", "attrs": {"id": mentioned_user.id}}],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        # Verify slug is passed as 3rd argument
        assert call_args[0][2] == "/replay/test-replay-id"

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_slug_defaults_to_empty_string_when_not_provided(self, mock_send_email) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(self.organization, "no_slug@posthog.com", None)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "",
                "scope": "Replay",
                "item_id": "test-replay-id",
                "rich_content": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "ph-mention", "attrs": {"id": mentioned_user.id}}],
                        }
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_send_email.called
        call_args = mock_send_email.call_args
        # Verify slug defaults to empty string
        assert call_args[0][2] == ""

    def test_soft_delete_comment_without_providing_content(self) -> None:
        # Create a comment
        existing = self._create_comment({"content": "This is a comment"})

        # Soft delete by setting deleted=True without providing content
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing['id']}",
            {"deleted": True},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["deleted"] is True
        assert response.json()["content"] == "This is a comment"

    def test_soft_deleted_comments_excluded_from_list_by_default(self) -> None:
        # Create comments
        self._create_comment({"content": "comment 1"})
        comment_to_delete = self._create_comment({"content": "comment 2"})

        # Verify both exist
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert len(response.json()["results"]) == 2

        # Soft delete
        self.client.patch(
            f"/api/projects/{self.team.id}/comments/{comment_to_delete['id']}",
            {"deleted": True},
        )

        # Verify deleted comment is excluded from list
        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["content"] == "comment 1"

    def test_hard_delete_returns_method_not_allowed(self) -> None:
        existing = self._create_comment({"content": "This is a comment"})

        response = self.client.delete(f"/api/projects/{self.team.id}/comments/{existing['id']}")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def _scoped_key_headers(self, scopes: list[str]) -> dict[str, str]:
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.utils import generate_random_token_personal

        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="scoped", user=self.user, secure_value=hash_key_value(value), scopes=scopes)
        return {"authorization": f"Bearer {value}"}

    @parameterized.expand(
        [
            ("comment_read_ticket_discussions", ["comment:read"], "Ticket", status.HTTP_403_FORBIDDEN),
            ("comment_read_ticket_messages", ["comment:read"], "conversations_ticket", status.HTTP_403_FORBIDDEN),
            ("ticket_read_ticket_discussions", ["ticket:read"], "Ticket", status.HTTP_200_OK),
            ("comment_read_other_scopes", ["comment:read"], "Notebook", status.HTTP_200_OK),
        ]
    )
    def test_ticket_scoped_comments_require_ticket_api_scope(
        self, _name: str, scopes: list[str], comment_scope: str, expected_status: int
    ) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/comments?scope={comment_scope}",
            headers=self._scoped_key_headers(scopes),
        )
        assert response.status_code == expected_status

    @parameterized.expand([("exact", "Ticket"), ("whitespace_padded", " Ticket ")])
    def test_creating_ticket_scoped_comment_requires_ticket_write_scope(self, _name: str, scope: str) -> None:
        # DRF trims the scope before storing it, so a padded value must not read as non-ticket here.
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "internal note", "scope": scope, "item_id": "some-ticket-id"},
            headers=self._scoped_key_headers(["comment:write"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_ticket_scoped_comments_excluded_from_default_list(self) -> None:
        Comment.objects.create(team=self.team, scope="Ticket", item_id="t1", content="discussion", created_by=self.user)
        Comment.objects.create(
            team=self.team, scope="conversations_ticket", item_id="t1", content="message", created_by=self.user
        )
        self._create_comment({"scope": "Notebook", "content": "normal"})

        response = self.client.get(f"/api/projects/{self.team.id}/comments")
        assert response.status_code == status.HTTP_200_OK
        assert [c["scope"] for c in response.json()["results"]] == ["Notebook"]

    @mock.patch("posthog.api.comments.CommentViewSet._slack_mirror_flag_enabled", return_value=True)
    def test_email_thread_comments_are_blocked_from_generic_comment_surfaces(self, _flag: mock.Mock) -> None:
        comment = Comment.objects.create(
            team=self.team,
            scope="EmailThread",
            item_id="019fed13-8204-76cd-8c0c-5d02cf10fc02",
            content="Private email body",
            created_by=self.user,
        )

        unscoped = self.client.get(f"/api/projects/{self.team.id}/comments")
        scoped = self.client.get(f"/api/projects/{self.team.id}/comments?scope=EmailThread")
        detail = self.client.get(f"/api/projects/{self.team.id}/comments/{comment.id}")
        update = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{comment.id}",
            {"content": "Rewritten email body"},
        )
        create = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "scope": "EmailThread",
                "item_id": "019fed13-8204-76cd-8c0c-5d02cf10fc02",
                "content": "New email body",
            },
        )
        slack = self.client.post(
            f"/api/projects/{self.team.id}/comments/{comment.id}/send_to_slack/",
            {"integration_id": 1, "channel_id": "C1"},
        )

        assert comment.id not in {row["id"] for row in unscoped.json()["results"]}
        assert scoped.json()["results"] == []
        assert detail.status_code == status.HTTP_404_NOT_FOUND
        assert update.status_code == status.HTTP_404_NOT_FOUND
        assert create.status_code == status.HTTP_403_FORBIDDEN
        assert slack.status_code == status.HTTP_404_NOT_FOUND
        assert not ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="EmailThread",
            item_id=comment.item_id,
        ).exists()

    def test_ticket_scoped_comment_detail_actions_work_for_session_users(self) -> None:
        # Detail actions carry no scope param; the default-list exclusion must not 404 them.
        comment = Comment.objects.create(
            team=self.team, scope="Ticket", item_id="t1", content="discussion", created_by=self.user
        )
        response = self.client.get(f"/api/projects/{self.team.id}/comments/{comment.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["scope"] == "Ticket"

    def test_ticket_scoped_comment_detail_requires_ticket_api_scope(self) -> None:
        comment = Comment.objects.create(
            team=self.team, scope="Ticket", item_id="t1", content="discussion", created_by=self.user
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/comments/{comment.id}",
            headers=self._scoped_key_headers(["comment:read"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_query_scope_cannot_override_ticket_body_scope_on_create(self) -> None:
        # ?scope= filters lists; the created object's scope comes from the body — the body decides.
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments?scope=Notebook",
            {"content": "internal note", "scope": "Ticket", "item_id": "some-ticket-id"},
            headers=self._scoped_key_headers(["comment:write"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_body_scope_cannot_override_stored_ticket_scope_on_detail(self) -> None:
        comment = Comment.objects.create(
            team=self.team, scope="Ticket", item_id="t1", content="discussion", created_by=self.user
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{comment.id}",
            {"scope": "Notebook", "content": "rewritten"},
            headers=self._scoped_key_headers(["comment:write"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_reserved_slack_sync_item_context_keys_are_stripped(self) -> None:
        # Forged sync state would let a caller suppress mirroring or spoof Slack attribution.
        created = self._create_comment(
            {"item_context": {"from_slack": True, "slack_synced_ts": "123.456", "is_emoji": False}}
        )
        assert created["item_context"] == {"is_emoji": False}

    def test_ticket_scope_key_cannot_write_non_ticket_comment_via_body_scope(self) -> None:
        comment = Comment.objects.create(
            team=self.team, scope="Notebook", item_id="n1", content="note", created_by=self.user
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{comment.id}",
            {"scope": "Ticket", "content": "rewritten"},
            headers=self._scoped_key_headers(["ticket:write"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_comment_key_cannot_attach_reply_to_ticket_thread(self) -> None:
        # The parent's stored scope gates a reply's create — a non-ticket body scope must not
        # smuggle a reply into a ticket discussion (it would render in the ticket's /thread).
        parent = Comment.objects.create(
            team=self.team, scope="Ticket", item_id="t1", content="root", created_by=self.user
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "sneaky", "scope": "Notebook", "item_id": "n1", "source_comment": str(parent.id)},
            headers=self._scoped_key_headers(["comment:write"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert Comment.objects.filter(source_comment=parent).count() == 0

    def test_reply_scope_must_match_parent_scope(self) -> None:
        # Even with both API scopes granted, a cross-scope reply row must never exist: a Ticket
        # reply under a non-ticket parent would leak through the parent's /thread to comment:read.
        parent = Comment.objects.create(
            team=self.team, scope="Notebook", item_id="n1", content="root", created_by=self.user
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "cross-scope", "scope": "Ticket", "item_id": "t1", "source_comment": str(parent.id)},
            headers=self._scoped_key_headers(["ticket:write", "comment:write"]),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Comment.objects.filter(source_comment=parent).count() == 0

    def test_reply_cannot_reference_another_teams_comment(self) -> None:
        other_team = self.organization.teams.create(name="other")
        parent = Comment.objects.create(
            team=other_team, scope="Notebook", item_id="n1", content="root", created_by=self.user
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "cross-team", "scope": "Notebook", "item_id": "n1", "source_comment": str(parent.id)},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Comment.objects.filter(source_comment=parent).count() == 0

    def test_get_body_cannot_mask_ticket_query_scope(self) -> None:
        # A JSON body on a GET selects nothing — the query scope drives the queryset and must
        # drive the requirement.
        response = self.client.generic(
            "GET",
            f"/api/projects/{self.team.id}/comments?scope=Ticket",
            data='{"scope": "Notebook"}',
            content_type="application/json",
            headers=self._scoped_key_headers(["comment:read"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_thread_query_scope_requires_ticket_access(self) -> None:
        # The stored parent scope must not mask a ticket query scope that still filters the replies.
        parent = Comment.objects.create(
            team=self.team, scope="Notebook", item_id="n1", content="root", created_by=self.user
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/comments/{parent.id}/thread?scope=Ticket",
            headers=self._scoped_key_headers(["comment:read"]),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_ticket_comment_content_masked_in_activity_log(self) -> None:
        # Activity logs are readable with activity_log:read only — ticket bodies must not leak there.
        Comment.objects.create(
            team=self.team, scope="Ticket", item_id="t1", content="internal discussion", created_by=self.user
        )
        entry = ActivityLog.objects.filter(team_id=self.team.id, scope="Ticket", activity="commented").first()
        assert entry is not None
        assert entry.detail is not None
        assert entry.detail["changes"][0]["after"] == "masked"
        assert "internal discussion" not in str(entry.detail)

    def test_ticket_reply_content_masked_in_activity_log(self) -> None:
        # Replies are logged under the parent thread's "Comment" activity scope, not the ticket
        # scope — masking must key off the comment's own scope or reply bodies leak.
        parent = Comment.objects.create(
            team=self.team, scope="Ticket", item_id="t1", content="internal discussion", created_by=self.user
        )
        Comment.objects.create(
            team=self.team,
            scope="Ticket",
            item_id="t1",
            content="secret reply",
            created_by=self.user,
            source_comment=parent,
        )
        entry = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Comment", item_id=str(parent.id), activity="commented"
        ).first()
        assert entry is not None
        assert entry.detail is not None
        assert entry.detail["changes"][0]["after"] == "masked"
        assert "secret reply" not in str(entry.detail)

    def test_non_ticket_comment_content_not_masked_in_activity_log(self) -> None:
        Comment.objects.create(
            team=self.team, scope="Notebook", item_id="n1", content="plain note", created_by=self.user
        )
        entry = ActivityLog.objects.filter(team_id=self.team.id, scope="Notebook", activity="commented").first()
        assert entry is not None
        assert entry.detail is not None
        assert entry.detail["changes"][0]["after"] == "plain note"


# The Support composer posts its replies through this endpoint, and both gateways and operators
# retry those requests. The guard's own behavior is covered in
# products/conversations/backend/tests/test_reply_dedupe.py; these are the wiring cases.
class TestCommentsSupportReplyDedupe(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().flushall()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="dedupe-session",
            distinct_id="dedupe-user",
            status=Status.OPEN,
        )

    def _post(self, **overrides: Any) -> Any:
        payload: dict[str, Any] = {
            "content": "Have you tried clearing the cache?",
            "scope": "conversations_ticket",
            "item_id": str(self.ticket.id),
            "item_context": {"author_type": "support", "is_private": False},
        }
        payload.update(overrides)
        return self.client.post(f"/api/projects/{self.team.id}/comments", payload, format="json")

    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_retried_support_reply_returns_the_original_without_notifying_twice(
        self, mock_send_email: mock.MagicMock, mock_produce_events: mock.MagicMock
    ) -> None:
        mentioned = User.objects.create_and_join(self.organization, "mentioned-dedupe@posthog.com", None)
        rich_content = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "ph-mention", "attrs": {"id": mentioned.id}}]}],
        }

        first = self._post(rich_content=rich_content)
        second = self._post(rich_content=rich_content)

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["id"] == first.json()["id"]
        assert Comment.objects.filter(scope="conversations_ticket", item_id=str(self.ticket.id)).count() == 1
        assert mock_send_email.call_count == 1
        assert mock_produce_events.call_count == 1

    def test_reply_still_being_created_returns_a_conflict(self) -> None:
        fingerprint = ReplyFingerprint.build(
            team_id=self.team.id,
            created_by_id=self.user.id,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Have you tried clearing the cache?",
            rich_content=None,
            item_context={"author_type": "support", "is_private": False},
        )
        assert fingerprint is not None
        reserve(fingerprint)

        response = self._post()

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error_type"] == REPLY_IN_PROGRESS_ERROR_TYPE
        assert not Comment.objects.filter(scope="conversations_ticket").exists()

    @parameterized.expand(
        [
            ("internal_ticket_discussion", {"scope": "Ticket"}),
            ("customer_message", {"item_context": {"author_type": "customer", "is_private": False}}),
            ("task", {"is_task": True}),
            ("notebook_comment", {"scope": "Notebook", "item_context": None}),
        ]
    )
    def test_non_support_messages_are_still_created_twice(self, _name: str, overrides: dict[str, Any]) -> None:
        first = self._post(**overrides)
        second = self._post(**overrides)

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert second.json()["id"] != first.json()["id"]


TICKET_SCOPE_CASES = [("conversations_ticket",), ("Ticket",)]


class TestCommentsTicketAccessControl(APIBaseTest):
    """Ticket-carrying comments — customer messages (conversations_ticket) and internal ticket
    discussions (Ticket) — are read/written through this generic endpoint by the Support UI (not
    TicketViewSet), so object-level ticket RBAC must be enforced here too, or a denied member can
    read/write a ticket's contents directly."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        self.member = User.objects.create_and_join(self.organization, "ticket-member@posthog.com", "password")
        self.client.force_login(self.member)
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="acl-session",
            distinct_id="acl-user",
            status=Status.OPEN,
        )
        AccessControl.objects.create(
            resource="ticket",
            resource_id=str(self.ticket.id),
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="none",
        )
        for scope in ("conversations_ticket", "Ticket"):
            Comment.objects.create(
                team=self.team,
                scope=scope,
                item_id=str(self.ticket.id),
                content="a private message",
            )

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_denied_member_cannot_list_ticket_messages(self, scope: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope={scope}&item_id={self.ticket.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_denied_member_cannot_retrieve_ticket_message_by_id(self, scope: str) -> None:
        # Detail actions carry no scope param, so the queryset-level ticket filter never runs.
        message = Comment.objects.get(scope=scope, item_id=str(self.ticket.id))

        response = self.client.get(f"/api/projects/{self.team.id}/comments/{message.id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_denied_member_cannot_create_ticket_message(self, scope: str) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "sneaking in a reply",
                "scope": scope,
                "item_id": str(self.ticket.id),
                "item_context": {"author_type": "support", "is_private": False},
            },
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Comment.objects.filter(item_id=str(self.ticket.id), content="sneaking in a reply").exists()

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_viewer_can_list_but_not_create_ticket_message(self, scope: str) -> None:
        AccessControl.objects.filter(resource_id=str(self.ticket.id)).update(access_level="viewer")

        list_response = self.client.get(f"/api/projects/{self.team.id}/comments?scope={scope}&item_id={self.ticket.id}")
        assert len(list_response.json()["results"]) == 1

        create_response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "viewer trying to reply",
                "scope": scope,
                "item_id": str(self.ticket.id),
                "item_context": {"author_type": "support", "is_private": False},
            },
        )
        assert create_response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_editor_can_list_and_create_ticket_message(self, scope: str) -> None:
        AccessControl.objects.filter(resource_id=str(self.ticket.id)).update(access_level="editor")

        create_response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "editor reply",
                "scope": scope,
                "item_id": str(self.ticket.id),
                "item_context": {"author_type": "support", "is_private": False},
            },
        )
        assert create_response.status_code == status.HTTP_201_CREATED

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_creator_downgraded_to_viewer_cannot_edit_own_ticket_message(self, scope: str) -> None:
        AccessControl.objects.filter(resource_id=str(self.ticket.id)).update(access_level="editor")
        own_message = Comment.objects.create(
            team=self.team,
            created_by=self.member,
            scope=scope,
            item_id=str(self.ticket.id),
            content="my reply",
        )
        AccessControl.objects.filter(resource_id=str(self.ticket.id)).update(access_level="viewer")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{own_message.id}?scope={scope}",
            {"content": "edited after being downgraded"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        own_message.refresh_from_db()
        assert own_message.content == "my reply"

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_cannot_rescope_existing_comment_into_denied_ticket(self, scope: str) -> None:
        own_comment = Comment.objects.create(
            team=self.team,
            created_by=self.member,
            scope="Notebook",
            item_id="1",
            content="a notebook comment",
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{own_comment.id}",
            {"scope": scope, "item_id": str(self.ticket.id)},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        own_comment.refresh_from_db()
        assert own_comment.scope == "Notebook"

    def _deny_ticket_resource(self) -> None:
        AccessControl.objects.filter(resource_id=str(self.ticket.id)).delete()
        AccessControl.objects.create(
            resource="ticket",
            resource_id=None,
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="none",
        )

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_member_denied_ticket_resource_cannot_list_messages_across_tickets(self, scope: str) -> None:
        self._deny_ticket_resource()

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope={scope}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_member_denied_ticket_resource_still_lists_messages_of_specifically_granted_ticket(
        self, scope: str
    ) -> None:
        self._deny_ticket_resource()
        AccessControl.objects.create(
            resource="ticket",
            resource_id=str(self.ticket.id),
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="viewer",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/comments?scope={scope}")

        assert [result["content"] for result in response.json()["results"]] == ["a private message"]

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_viewer_cannot_complete_ticket_task(self, scope: str) -> None:
        AccessControl.objects.filter(resource_id=str(self.ticket.id)).update(access_level="viewer")
        task = Comment.objects.create(
            team=self.team,
            created_by=self.member,
            scope=scope,
            item_id=str(self.ticket.id),
            content="a ticket task",
            is_task=True,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments/{task.id}/complete?scope={scope}",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        task.refresh_from_db()
        assert task.completed_at is None

    @parameterized.expand(TICKET_SCOPE_CASES)
    def test_cannot_reply_into_a_denied_ticket_using_an_editable_ticket_item_id(self, scope: str) -> None:
        # /thread selects by source_comment_id, so a reply naming a ticket the member can edit
        # would still render in the denied ticket's thread if item_id weren't pinned to the parent.
        editable_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="editable-session",
            distinct_id="editable-user",
            status=Status.OPEN,
        )
        AccessControl.objects.create(
            resource="ticket",
            resource_id=str(editable_ticket.id),
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="editor",
        )
        parent = Comment.objects.get(scope=scope, item_id=str(self.ticket.id))

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "injected into a denied ticket",
                "scope": scope,
                "item_id": str(editable_ticket.id),
                "source_comment": str(parent.id),
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Comment.objects.filter(source_comment=parent).exists()


class TestDiscussionMentionInternalEvents(APIBaseTest, QueryMatchingTest):
    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_produces_internal_event_on_comment_create(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(
            self.organization, "event_mention@posthog.com", None, first_name="MentionedUser"
        )

        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Check this out",
                "scope": "Notebook",
                "item_id": "123",
                "mentions": [mentioned_user.id],
            },
        )

        assert mock_produce_event.called
        call_args = mock_produce_event.call_args
        assert call_args.kwargs["team_id"] == self.team.id
        event = call_args.kwargs["event"]
        assert event.event == "$discussion_mention_created"
        assert event.properties["mentioned_user_id"] == mentioned_user.id
        assert event.properties["mentioned_user_email"] == mentioned_user.email
        assert event.properties["scope"] == "Notebook"
        assert event.properties["item_id"] == "123"

    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_produces_internal_event_on_comment_update(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(
            self.organization, "update_mention@posthog.com", None, first_name="MentionedUser"
        )

        existing = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "Original", "scope": "Notebook"},
        )

        mock_produce_event.reset_mock()

        self.client.patch(
            f"/api/projects/{self.team.id}/comments/{existing.json()['id']}",
            {"content": "Updated", "mentions": [mentioned_user.id]},
        )

        assert mock_produce_event.called
        event = mock_produce_event.call_args.kwargs["event"]
        assert event.event == "$discussion_mention_created"

    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_cross_organization_mentions_are_filtered_out(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        from posthog.models import Organization, User

        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_and_join(other_org, "outsider@other.com", None, first_name="Outsider")

        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Mentioning external user",
                "scope": "Notebook",
                "mentions": [other_user.id],
            },
        )

        mock_send_email.assert_not_called()
        mock_produce_event.assert_not_called()

    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_self_mentions_do_not_produce_events(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "I mention myself",
                "scope": "Notebook",
                "mentions": [self.user.id],
            },
        )

        mock_produce_event.assert_not_called()

    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_event_properties_include_correct_user_data(
        self, mock_send_email: mock.MagicMock, mock_produce_event: mock.MagicMock
    ) -> None:
        from posthog.models import User

        mentioned_user = User.objects.create_and_join(
            self.organization, "data_test@posthog.com", None, first_name="TestUser"
        )

        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "Test content",
                "scope": "Insight",
                "item_id": "456",
                "mentions": [mentioned_user.id],
                "slug": "/insights/456",
            },
        )

        call_args = mock_produce_event.call_args
        event = call_args.kwargs["event"]
        person = call_args.kwargs["person"]

        assert event.properties["mentioned_user_id"] == mentioned_user.id
        assert event.properties["mentioned_user_email"] == "data_test@posthog.com"
        assert event.properties["mentioned_user_name"] == "TestUser"
        assert event.properties["commenter_user_id"] == self.user.id
        assert event.properties["commenter_user_email"] == self.user.email
        assert event.properties["scope"] == "Insight"
        assert event.properties["item_id"] == "456"
        assert event.properties["slug"] == "/insights/456"
        assert event.properties["team_name"] == self.team.name

        assert person.id == str(self.user.id)


class TestCommentHelperFunctions(APIBaseTest):
    @parameterized.expand(
        [
            ("with_slug", "Notebook", "123", "/notebook/abc", "/notebook/abc#panel=discussion"),
            (
                "with_slug_already_has_panel",
                "Notebook",
                "123",
                "/notebook/abc#panel=discussion",
                "/notebook/abc#panel=discussion",
            ),
            ("without_slug_notebook", "Notebook", "123", "", "/notebooks/123#panel=discussion"),
            ("without_slug_insight", "Insight", "456", "", "/insights/456#panel=discussion"),
            ("without_slug_dashboard", "Dashboard", "789", "", "/dashboard/789#panel=discussion"),
            ("without_slug_replay", "Replay", "rec_123", "", "/replay/rec_123#panel=discussion"),
            ("without_slug_feature_flag", "FeatureFlag", "10", "", "/feature_flags/10#panel=discussion"),
            ("unknown_scope_fallback", "UnknownScope", "123", "", "#panel=discussion"),
            # item_id is client-supplied free text — mrkdwn/URL control chars must be encoded.
            (
                "item_id_with_mrkdwn_chars",
                "Notebook",
                "x|<!channel>y",
                "",
                "/notebooks/x%7C%3C%21channel%3Ey#panel=discussion",
            ),
        ]
    )
    def test_build_comment_item_url(self, name: str, scope: str, item_id: str, slug: str, expected_suffix: str) -> None:
        result = build_comment_item_url(scope, item_id, slug if slug else None)
        assert result == f"{settings.SITE_URL}{expected_suffix}"

    @parameterized.expand(
        [
            ("simple_text", {"type": "doc", "content": [{"type": "text", "text": "Hello"}]}, "Hello"),
            (
                "with_mention",
                {
                    "type": "doc",
                    "content": [{"type": "ph-mention", "attrs": {"id": 1, "label": "John"}}],
                },
                "@John",
            ),
            (
                "mixed_content",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Hey "},
                                {"type": "ph-mention", "attrs": {"id": 1, "label": "Jane"}},
                                {"type": "text", "text": " check this"},
                            ],
                        }
                    ],
                },
                "Hey @Jane check this",
            ),
            ("empty_content", None, ""),
            ("empty_dict", {}, ""),
        ]
    )
    def test_extract_plain_text_from_rich_content(self, name: str, rich_content: dict | None, expected: str) -> None:
        result = extract_plain_text_from_rich_content(rich_content)
        assert result == expected


class TestCommentTasks(APIBaseTest, QueryMatchingTest):
    def _create_task(self, data: dict | None = None) -> Any:
        payload = {"content": "fix the empty-state copy", "scope": "Replay", "is_task": True}
        if data:
            payload.update(data)
        return self.client.post(f"/api/projects/{self.team.id}/comments", payload).json()

    def test_creates_task_successfully(self) -> None:
        response = self._create_task()
        assert response["is_task"] is True
        assert response["completed_at"] is None
        assert response["completed_by"] is None

    def test_default_is_task_is_false(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "regular comment", "scope": "Notebook"},
        ).json()
        assert response["is_task"] is False

    @parameterized.expand(
        [
            (
                "reply_cannot_be_task",
                lambda self: {
                    "content": "reply",
                    "scope": "Replay",
                    "is_task": True,
                    "source_comment": self._create_task()["id"],
                },
                "Replies cannot be tasks.",
            ),
            (
                "emoji_reaction_cannot_be_task",
                lambda _self: {
                    "content": "👍",
                    "scope": "Replay",
                    "is_task": True,
                    "item_context": {"is_emoji": True},
                },
                "Emoji reactions cannot be tasks.",
            ),
        ]
    )
    def test_invalid_task_creation(self, _name: str, payload_fn: Any, expected_detail: str) -> None:
        payload = payload_fn(self)
        response = self.client.post(f"/api/projects/{self.team.id}/comments", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == expected_detail

    def test_is_task_immutable_after_creation(self) -> None:
        task = self._create_task()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{task['id']}",
            {"is_task": False},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Cannot change task state after creation."

        # Same value is a no-op and should be accepted
        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{task['id']}",
            {"is_task": True, "content": "edited"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_task"] is True

    def test_complete_and_reopen_roundtrip(self) -> None:
        task = self._create_task()

        complete_response = self.client.post(f"/api/projects/{self.team.id}/comments/{task['id']}/complete")
        assert complete_response.status_code == status.HTTP_200_OK
        assert complete_response.json()["completed_at"] is not None
        assert complete_response.json()["completed_by"]["id"] == self.user.id

        # Already complete -> 400
        repeat = self.client.post(f"/api/projects/{self.team.id}/comments/{task['id']}/complete")
        assert repeat.status_code == status.HTTP_400_BAD_REQUEST
        assert repeat.json()["detail"] == "Task is already complete"

        reopen_response = self.client.post(f"/api/projects/{self.team.id}/comments/{task['id']}/reopen")
        assert reopen_response.status_code == status.HTTP_200_OK
        assert reopen_response.json()["completed_at"] is None
        assert reopen_response.json()["completed_by"] is None

        # Already open -> 400
        repeat = self.client.post(f"/api/projects/{self.team.id}/comments/{task['id']}/reopen")
        assert repeat.status_code == status.HTTP_400_BAD_REQUEST
        assert repeat.json()["detail"] == "Task is already open"

    @parameterized.expand(
        [
            ("complete_endpoint", "complete"),
            ("reopen_endpoint", "reopen"),
        ]
    )
    def test_state_endpoints_reject_non_tasks(self, _name: str, endpoint: str) -> None:
        comment = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "regular", "scope": "Notebook"},
        ).json()

        response = self.client.post(f"/api/projects/{self.team.id}/comments/{comment['id']}/{endpoint}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_complete_writes_activity_log_entry(self) -> None:
        recording_id = "01964c81-1234-5678-90ab-cdef01234567"
        task = self._create_task({"item_id": recording_id})
        self.client.post(f"/api/projects/{self.team.id}/comments/{task['id']}/complete")
        self.client.post(f"/api/projects/{self.team.id}/comments/{task['id']}/reopen")

        activities = list(
            ActivityLog.objects.filter(
                team_id=self.team.id,
                item_id=recording_id,
                activity__in=["completed task", "reopened task"],
            ).order_by("created_at")
        )
        assert [a.activity for a in activities] == ["completed task", "reopened task"]
        assert all(a.scope == "Replay" for a in activities)

    @parameterized.expand(
        [
            ("complete_endpoint_404", "complete"),
            ("reopen_endpoint_404", "reopen"),
        ]
    )
    def test_state_endpoints_404_on_soft_deleted_task(self, _name: str, endpoint: str) -> None:
        task = self._create_task()
        self.client.patch(f"/api/projects/{self.team.id}/comments/{task['id']}", {"deleted": True})

        response = self.client.post(f"/api/projects/{self.team.id}/comments/{task['id']}/{endpoint}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("null_on_task_rejected", True, status.HTTP_400_BAD_REQUEST),
            ("null_on_comment_rejected", False, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_patch_is_task_null_is_rejected(self, _name: str, create_as_task: bool, expected_status: int) -> None:
        if create_as_task:
            comment_id = self._create_task()["id"]
        else:
            comment_id = self.client.post(
                f"/api/projects/{self.team.id}/comments",
                {"content": "regular", "scope": "Notebook"},
            ).json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{comment_id}",
            {"is_task": None},
            format="json",
        )
        assert response.status_code == expected_status

    def test_legacy_null_is_task_rows_serialize_as_false(self) -> None:
        # Simulate a row written before this feature shipped, with is_task=None.
        legacy = Comment.objects.create(team=self.team, scope="Notebook", content="legacy", created_by=self.user)
        Comment.objects.filter(id=legacy.id).update(is_task=None)

        response = self.client.get(f"/api/projects/{self.team.id}/comments/{legacy.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_task"] is False

    @parameterized.expand(
        [
            ("kind_any", "kind=any", 3),
            ("kind_comment", "kind=comment", 1),
            ("kind_task", "kind=task", 2),
            ("kind_task_open", "kind=task&completed=open", 1),
            ("kind_task_completed", "kind=task&completed=completed", 1),
            ("completed_open_without_kind_ignored", "completed=open", 3),
            ("completed_completed_without_kind_ignored", "completed=completed", 3),
        ]
    )
    def test_kind_and_completed_filters(self, _name: str, query: str, expected_count: int) -> None:
        # 1 plain comment, 1 open task, 1 completed task
        self._create_task({"content": "open task"})
        completed_task = self._create_task({"content": "completed task"})
        self.client.post(f"/api/projects/{self.team.id}/comments/{completed_task['id']}/complete")
        self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "regular", "scope": "Notebook"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/comments?{query}")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == expected_count
