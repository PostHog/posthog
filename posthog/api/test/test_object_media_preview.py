import uuid

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import EventDefinition, ObjectMediaPreview, UploadedMedia, User

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

    def test_create_links_only_the_uploaded_media(self):
        event_definition = EventDefinition.objects.create(team=self.team, name="purchase")
        media = UploadedMedia.objects.create(team=self.team, file_name="screenshot.png", content_type="image/png")
        asset = ExportedAsset.objects.create(team=self.team, export_format="text/csv", created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/object_media_previews/",
            {
                "event_definition_id": str(event_definition.pk),
                "uploaded_media_id": str(media.pk),
                # Asset ids are integers, which a UUID field accepted in this form
                "exported_asset_id": str(uuid.UUID(int=asset.pk)),
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
        media_url = list_response.json()["results"][0]["media_url"]
        if expects_url:
            assert "token=" in media_url
            assert preferred_response.json()["media_url"] == media_url
        else:
            assert media_url == ""
            assert preferred_response.status_code == status.HTTP_404_NOT_FOUND
