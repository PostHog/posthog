from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import EventDefinition, ObjectMediaPreview, UploadedMedia
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal


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

    @parameterized.expand(
        [
            ("with_read_scope", ["event_definition:read"], status.HTTP_200_OK),
            ("without_read_scope", ["insight:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_preferred_for_event_with_personal_api_key(self, _name, scopes, expected_status):
        event_definition, previews = self._create_previews(1)
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="key", user=self.user, secure_value=hash_key_value(value), scopes=scopes)
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.pk}/object_media_previews/preferred_for_event/"
            f"?event_definition={event_definition.pk}",
            headers={"Authorization": f"Bearer {value}"},
        )

        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_200_OK:
            assert response.json()["id"] == str(previews[0].id)
