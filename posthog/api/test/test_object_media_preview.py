import uuid

from posthog.test.base import APIBaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import ObjectMediaPreview, Team, UploadedMedia, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.session_recordings.models.session_recording import SessionRecording

from products.event_definitions.backend.models import EventDefinition
from products.exports.backend.models.exported_asset import ExportedAsset


class TestObjectMediaPreviewAPI(APIBaseTest):
    def _create_previews(self, count: int) -> tuple[EventDefinition, list[ObjectMediaPreview]]:
        event_definition = EventDefinition.objects.create(team=self.team, name="purchase")
        previews = []
        for index in range(count):
            media = UploadedMedia.objects.create(
                team=self.team, file_name=f"screenshot_{index}.png", content_type="image/png"
            )
            previews.append(
                ObjectMediaPreview.objects.create(
                    team=self.team, event_definition=event_definition, uploaded_media=media
                )
            )
        return event_definition, previews

    def _get_page(self, event_definition: EventDefinition, limit: int, offset: int) -> list[str]:
        response = self.client.get(
            f"/api/projects/{self.team.pk}/object_media_previews/"
            f"?event_definition={event_definition.pk}&limit={limit}&offset={offset}"
        )
        assert response.status_code == status.HTTP_200_OK
        return [result["id"] for result in response.json()["results"]]

    def test_pagination_returns_every_preview_once_when_update_times_are_tied(self):
        event_definition, previews = self._create_previews(6)
        ObjectMediaPreview.objects.filter(team=self.team).update(updated_at=timezone.now())

        seen = []
        for offset in (0, 2, 4):
            seen += self._get_page(event_definition, limit=2, offset=offset)

        # Tied rows need a total order, or a page boundary can skip or repeat a preview
        assert seen == sorted((str(preview.id) for preview in previews), reverse=True)

    def test_list_requires_an_event_definition(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/object_media_previews/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_links_only_the_uploaded_media(self):
        event_definition = EventDefinition.objects.create(team=self.team, name="purchase")
        media = UploadedMedia.objects.create(team=self.team, file_name="screenshot.png", content_type="image/png")
        response = self.client.post(
            f"/api/projects/{self.team.pk}/object_media_previews/",
            {
                "event_definition_id": str(event_definition.pk),
                "uploaded_media_id": str(media.pk),
                "exported_asset_id": str(uuid.uuid4()),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        preview = ObjectMediaPreview.objects.get(id=response.json()["id"])
        assert preview.uploaded_media_id == media.pk
        assert preview.exported_asset_id is None

    @parameterized.expand(
        [
            ("own_export", "self", None, True),
            ("other_members_export", "other", None, False),
            ("event_screenshot", None, "session-1", True),
        ]
    )
    def test_exported_asset_media_url_follows_export_access(self, _name, created_by, session_recording_id, expects_url):
        event_definition = EventDefinition.objects.create(team=self.team, name="purchase")
        author = {
            "self": self.user,
            "other": User.objects.create_and_join(self.organization, "other@example.com", "password"),
            None: None,
        }[created_by]
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format="image/png",
            created_by=author,
            export_context={"session_recording_id": session_recording_id} if session_recording_id else None,
        )
        ObjectMediaPreview.objects.create(team=self.team, event_definition=event_definition, exported_asset=asset)

        list_response = self.client.get(
            f"/api/projects/{self.team.pk}/object_media_previews/?event_definition={event_definition.pk}"
        )
        preferred_response = self.client.get(
            f"/api/projects/{self.team.pk}/object_media_previews/preferred_for_event/?event_definition={event_definition.pk}"
        )

        assert list_response.status_code == status.HTTP_200_OK
        results = list_response.json()["results"]
        if expects_url:
            assert "token=" in results[0]["media_url"]
            assert preferred_response.json()["media_url"] == results[0]["media_url"]
        else:
            assert results == []
            assert preferred_response.status_code == status.HTTP_404_NOT_FOUND

    def test_preferred_for_event_skips_a_newer_export_the_viewer_may_not_read(self):
        event_definition = EventDefinition.objects.create(team=self.team, name="purchase")
        screenshot = ExportedAsset.objects.create(
            team=self.team, export_format="image/png", export_context={"session_recording_id": "session-1"}
        )
        visible = ObjectMediaPreview.objects.create(
            team=self.team, event_definition=event_definition, exported_asset=screenshot
        )
        other_member = User.objects.create_and_join(self.organization, "other@example.com", "password")
        hidden_asset = ExportedAsset.objects.create(team=self.team, export_format="text/csv", created_by=other_member)
        ObjectMediaPreview.objects.create(
            team=self.team, event_definition=event_definition, exported_asset=hidden_asset
        )

        response = self.client.get(
            f"/api/projects/{self.team.pk}/object_media_previews/preferred_for_event/?event_definition={event_definition.pk}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(visible.id)

    @parameterized.expand(
        [
            ("object_media_previews", "/api/projects/{team}/object_media_previews/?event_definition={event}"),
            ("event_definitions", "/api/projects/{team}/event_definitions/"),
        ]
    )
    def test_screenshot_access_checks_stay_bounded_to_the_project(self, _name, path):
        event_definition = EventDefinition.objects.create(team=self.team, name="purchase")
        other_team = Team.objects.create(organization=self.organization, name="Other project")

        def add_screenshot(team: Team, session_id: str, event: EventDefinition) -> None:
            SessionRecording.objects.create(team=team, session_id=session_id, distinct_id="user")
            asset = ExportedAsset.objects.create(
                team=team, export_format="image/png", export_context={"session_recording_id": session_id}
            )
            ObjectMediaPreview.objects.create(team=team, event_definition=event, exported_asset=asset)

        add_screenshot(other_team, "other-project-session", EventDefinition.objects.create(team=other_team, name="x"))

        def capture() -> list[str]:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(path.format(team=self.team.pk, event=event_definition.pk))
            assert response.status_code == status.HTTP_200_OK
            return [query["sql"] for query in queries]

        add_screenshot(self.team, str(uuid.uuid4()), event_definition)
        capture()
        with_one = capture()
        for _ in range(3):
            add_screenshot(self.team, str(uuid.uuid4()), event_definition)
        with_four = capture()

        assert len(with_four) == len(with_one)
        assert not any("other-project-session" in sql for sql in with_four)
        assert not any('"posthog_exportedasset"."content"' in sql for sql in with_four)

    @parameterized.expand(
        [
            ("without_export_scope", ["event_definition:read"], 0),
            ("with_export_scope", ["event_definition:read", "export:read"], 1),
        ]
    )
    def test_scoped_key_needs_export_read_to_get_export_links(self, _name, scopes, expected_links):
        event_definition = EventDefinition.objects.create(team=self.team, name="purchase")
        asset = ExportedAsset.objects.create(team=self.team, export_format="text/csv", created_by=self.user)
        ObjectMediaPreview.objects.create(team=self.team, event_definition=event_definition, exported_asset=asset)
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(user=self.user, label="test", secure_value=hash_key_value(key), scopes=scopes)
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.pk}/object_media_previews/?event_definition={event_definition.pk}",
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == expected_links
