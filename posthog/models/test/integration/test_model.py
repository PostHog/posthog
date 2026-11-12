"""Tests for the Integration model: encryption, display_name dispatch."""

import json
import time
from typing import Optional, cast

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.integrations import IntegrationManager
from posthog.integrations.backend.django_backend import _reported_over_encrypted
from posthog.integrations.contracts import FrozenIntegrationRecord
from posthog.integrations.secret_reads import integration_secret_decrypt_counter
from posthog.models.instance_setting import set_instance_setting
from posthog.models.integration import Integration, SlackIntegration, UndecryptedIntegrationSecretError


def get_db_field_value(field, model_id):
    cursor = connection.cursor()
    cursor.execute(f"select {field} from posthog_integration where id='{model_id}';")
    return cursor.fetchone()[0]


def update_db_field_value(field, model_id, value):
    cursor = connection.cursor()
    cursor.execute(f"update posthog_integration set {field}='{value}' where id='{model_id}';")


class TestIntegrationModel(BaseTest):
    def create_integration(
        self, kind: str, config: Optional[dict] = None, sensitive_config: Optional[dict] = None
    ) -> Integration:
        _config = {"refreshed_at": int(time.time()), "expires_in": 3600}
        _sensitive_config = {"refresh_token": "REFRESH", "id_token": None}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(team=self.team, kind=kind, config=_config, sensitive_config=_sensitive_config)

    def test_sensitive_config_encrypted(self):
        # Fernet encryption is deterministic, but has a temporal component and utilizes os.urandom() for the IV
        with time_machine.travel("2024-01-01T00:01:00Z", tick=False):
            with patch("os.urandom", return_value=b"\x00" * 16):
                integration = self.create_integration("slack")

                assert integration.sensitive_config == {"refresh_token": "REFRESH", "id_token": None}
                assert (
                    get_db_field_value("sensitive_config", integration.id)
                    == '{"id_token": null, "refresh_token": "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAJgmFh-MNX9haUNHNfYLvULI6vSRYVd3o8xd4f8xBkWEWAa5RJ2ikOM2dsW5_9F7Mw=="}'
                )

                # update the value to non-encrypted and check it still loads

                update_db_field_value(
                    "sensitive_config", integration.id, '{"id_token": null, "refresh_token": "REFRESH2"}'
                )
                integration.refresh_from_db()
                assert integration.sensitive_config == {"id_token": None, "refresh_token": "REFRESH2"}
                assert (
                    get_db_field_value("sensitive_config", integration.id)
                    == '{"id_token": null, "refresh_token": "REFRESH2"}'
                )

                integration.save()
                # The field should now be encrypted
                assert integration.sensitive_config == {"id_token": None, "refresh_token": "REFRESH2"}
                assert (
                    get_db_field_value("sensitive_config", integration.id)
                    == '{"id_token": null, "refresh_token": "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAHlWz9QOMnXDvmix-z5lNG4v0VcO9lGWejmcE_BXHXPZ1wNkb-38JupntWbshBrfFQ=="}'
                )

    @parameterized.expand(
        [
            ("model_access_token", "model", "access_token"),
            ("model_refresh_token", "model", "refresh_token"),
            ("frozen_access_token", "frozen", "access_token"),
            ("frozen_refresh_token", "frozen", "refresh_token"),
        ]
    )
    def test_oauth_token_property_raises_if_still_encrypted(
        self, _name: str, record_type: str, field_name: str
    ) -> None:
        # `sensitive_config` uses `ignore_decrypt_errors=True`, so a value that fails to decrypt
        # under every configured key comes back as raw Fernet ciphertext instead of raising. If the
        # `access_token`/`refresh_token` properties didn't check for that, this ciphertext would
        # get sent straight to the third-party API as the live credential.
        sensitive_config = {field_name: "gAAAAABleftover=="}
        record: object = Integration(team=self.team, kind="stripe", sensitive_config=sensitive_config)
        if record_type == "frozen":
            record = FrozenIntegrationRecord(
                id=1,
                reference="1",
                team_id=self.team.id,
                kind="stripe",
                integration_id=None,
                config={},
                sensitive_config=sensitive_config,
                errors="",
                created_at=timezone.now(),
                created_by_id=None,
                auth_type="oauth",
                display_name="",
            )
        with pytest.raises(UndecryptedIntegrationSecretError):
            getattr(record, field_name)

    @parameterized.expand([("access_token",), ("refresh_token",)])
    def test_oauth_token_property_passes_through_decrypted_value(self, field_name: str) -> None:
        integration = Integration(team=self.team, kind="stripe", sensitive_config={field_name: "a-real-token"})
        assert getattr(integration, field_name) == "a-real-token"

    @parameterized.expand(
        [
            ("refresh_from_db_access_token", "refresh_from_db", "access_token"),
            ("refresh_from_db_refresh_token", "refresh_from_db", "refresh_token"),
            ("sdk_access_token", "sdk", "access_token"),
            ("sdk_refresh_token", "sdk", "refresh_token"),
        ]
    )
    def test_load_recovers_an_over_encrypted_value(self, _name: str, load: str, field_name: str) -> None:
        # Saving an integration whose secret failed to decrypt re-encrypts the ciphertext, so the
        # stored value ends up with an extra layer and one decrypt still leaves ciphertext behind.
        # The secret is intact underneath, so the connection must keep working.
        integration = self.create_integration("stripe", sensitive_config={field_name: "a-real-token"})
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))
        stored = json.loads(get_db_field_value("sensitive_config", integration.id))
        update_db_field_value(
            "sensitive_config",
            integration.id,
            json.dumps({**stored, field_name: field.encrypt(stored[field_name])}),
        )

        if load == "sdk":
            record = IntegrationManager.stripe.oauth.get(self.team.id, integration.id)
        else:
            integration.refresh_from_db()
            record = integration

        assert getattr(record, field_name) == "a-real-token"
        assert record.sensitive_config[field_name] == "a-real-token"

    def test_over_encrypted_row_is_reported_once_and_clean_row_does_no_decrypt(self) -> None:
        _reported_over_encrypted.clear()
        integration = self.create_integration("stripe", sensitive_config={"access_token": "a-real-token"})
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))
        stored = json.loads(get_db_field_value("sensitive_config", integration.id))
        update_db_field_value(
            "sensitive_config",
            integration.id,
            json.dumps({**stored, "access_token": field.encrypt(stored["access_token"])}),
        )
        counter = integration_secret_decrypt_counter.labels(kind="stripe", result="recovered")
        before = counter._value.get()

        with patch("posthog.integrations.backend.django_backend.logger") as mock_logger:
            for _ in range(3):
                loaded = Integration.objects.get(pk=integration.id)
                assert loaded.access_token == "a-real-token"

        assert counter._value.get() - before == 1
        assert mock_logger.warning.call_count == 1

        update_db_field_value("sensitive_config", integration.id, json.dumps(stored))
        with patch.object(EncryptedJSONField, "decrypt_all_layers") as decrypt_all_layers:
            Integration.objects.get(pk=integration.id)
        decrypt_all_layers.assert_not_called()

    def test_unreadable_value_is_not_reported_as_recovered_and_is_refused(self) -> None:
        _reported_over_encrypted.clear()
        integration = self.create_integration("stripe", sensitive_config={"access_token": "a-real-token"})
        update_db_field_value("sensitive_config", integration.id, json.dumps({"access_token": "gAAAAABleftover=="}))
        counter = integration_secret_decrypt_counter.labels(kind="stripe", result="recovered")
        before = counter._value.get()

        loaded = Integration.objects.get(pk=integration.id)

        assert counter._value.get() == before
        with pytest.raises(UndecryptedIntegrationSecretError):
            _ = loaded.access_token

    def test_slack_integration_config(self):
        set_instance_setting("SLACK_APP_CLIENT_ID", None)
        set_instance_setting("SLACK_APP_CLIENT_SECRET", None)
        set_instance_setting("SLACK_APP_SIGNING_SECRET", None)

        assert not SlackIntegration.slack_config() == {}

        set_instance_setting("SLACK_APP_CLIENT_ID", "client-id")
        set_instance_setting("SLACK_APP_CLIENT_SECRET", "client-secret")
        set_instance_setting("SLACK_APP_SIGNING_SECRET", "not-so-secret")

        assert SlackIntegration.slack_config() == {
            "SLACK_APP_CLIENT_ID": "client-id",
            "SLACK_APP_CLIENT_SECRET": "client-secret",
            "SLACK_APP_SIGNING_SECRET": "not-so-secret",
        }


class TestPinterestAdsIntegrationDisplayName(BaseTest):
    @parameterized.expand(
        [
            (
                "business",
                {"id": "1", "username": "13x6ppss87fecv1q790xh1orhyp9th", "business_name": "Posthog Inc"},
                "Posthog Inc",
            ),
            ("personal", {"id": "1", "username": "javierposthog", "business_name": ""}, "javierposthog"),
            # Older connections predate business_name being stored.
            ("legacy", {"id": "1", "username": "javierposthog"}, "javierposthog"),
        ]
    )
    def test_display_name_prefers_business_name(self, _name: str, config: dict, expected: str) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind="pinterest-ads",
            config=config,
            integration_id=config["id"],
        )
        assert integration.display_name == expected


class TestTikTokAdsIntegrationDisplayName(BaseTest):
    @parameterized.expand(
        [
            (
                "email_wins_over_display_name",
                {
                    "advertiser_ids": ["7554133187111469074"],
                    "user_email": "e***g@posthog.com",
                    "user_display_name": "user1140434302514",
                },
                "e***g@posthog.com",
            ),
            ("neither_fetched_falls_back_to_id", {"advertiser_ids": ["7554133187111469074"]}, "7554133187111469074"),
        ]
    )
    def test_display_name_prefers_user_email(self, _name: str, config: dict, expected: str) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind="tiktok-ads",
            config=config,
            integration_id=",".join(config["advertiser_ids"]),
        )
        assert integration.display_name == expected


@override_settings(REDDIT_ADS_CLIENT_ID="reddit-client-id", REDDIT_ADS_CLIENT_SECRET="reddit-client-secret")
class TestRedditAdsIntegrationDisplayName(BaseTest):
    @parameterized.expand(
        [
            (
                "username",
                {"reddit_user_id": "t2_1tqubocxl4", "data.reddit_username": "javierposthog"},
                "javierposthog",
            ),
            ("legacy", {"reddit_user_id": "t2_1tqubocxl4"}, "t2_1tqubocxl4"),
        ]
    )
    def test_display_name_prefers_username(self, _name: str, config: dict, expected: str) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind="reddit-ads",
            config=config,
            integration_id=config["reddit_user_id"],
        )
        assert integration.display_name == expected
