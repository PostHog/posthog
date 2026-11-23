from collections.abc import Callable

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.integration import Integration


def _save(integration: Integration) -> None:
    integration.config = {"channel": "new"}
    integration.save()


def _save_update_fields(integration: Integration) -> None:
    integration.config = {"channel": "new"}
    integration.save(update_fields=["config"])


def _queryset_update(integration: Integration) -> None:
    Integration.objects.filter(pk=integration.pk).update(config={"channel": "new"})


def _bulk_update(integration: Integration) -> None:
    integration.config = {"channel": "new"}
    Integration.objects.bulk_update([integration], ["config"])


def _repository_cache_update(integration: Integration) -> None:
    Integration.objects.filter(pk=integration.pk).update(repository_cache_updated_at=timezone.now())


def _stale_save(integration: Integration) -> None:
    # The instance still holds the version from before this update.
    Integration.objects.filter(pk=integration.pk).update(errors="token expired")
    integration.config = {"channel": "new"}
    integration.save()


class TestIntegrationRowVersion(BaseTest):
    @parameterized.expand(
        [
            ("save", _save, 1),
            ("save_update_fields", _save_update_fields, 1),
            ("queryset_update", _queryset_update, 1),
            ("bulk_update", _bulk_update, 1),
            ("repository_cache_only", _repository_cache_update, 0),
            ("stale_instance_save", _stale_save, 2),
        ]
    )
    def test_row_version_after_write(self, _name: str, write: Callable[[Integration], None], expected: int) -> None:
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T1", config={"channel": "old"}
        )
        integration.refresh_from_db()
        self.assertEqual(integration.row_version, 0)

        write(integration)

        self.assertEqual(Integration.objects.values_list("row_version", flat=True).get(pk=integration.pk), expected)
