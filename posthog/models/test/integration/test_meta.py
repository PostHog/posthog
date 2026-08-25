"""Tests for the Meta Graph API integrations."""

import time

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.integration import FacebookPagesIntegration, InstagramIntegration, Integration, OauthIntegration


@override_settings(INSTAGRAM_APP_CLIENT_ID="instagram-client-id", INSTAGRAM_APP_CLIENT_SECRET="instagram-client-secret")
class TestInstagramIntegrationModel(BaseTest):
    def test_oauth_config(self):
        config = OauthIntegration.oauth_config_for_kind("instagram")

        # Same Graph version as the other Meta kinds: an older pin here makes the OAuth dialog
        # reject the permission set before anyone reaches a consent screen.
        assert config.authorize_url == "https://www.facebook.com/v25.0/dialog/oauth"
        assert config.token_url == "https://graph.facebook.com/v25.0/oauth/access_token"
        assert config.token_info_url == "https://graph.facebook.com/v25.0/me"
        assert config.client_id == "instagram-client-id"
        assert config.client_secret == "instagram-client-secret"
        assert config.id_path == "id"
        assert config.name_path == "name"
        # Instagram is reached through the Facebook page it is linked to, so the page scopes
        # are as load-bearing as the Instagram ones.
        assert set(config.scope.split(" ")) == {
            "instagram_basic",
            "instagram_manage_insights",
            "instagram_manage_comments",
            "pages_show_list",
            "pages_read_engagement",
        }

    @override_settings(INSTAGRAM_APP_CLIENT_ID="", INSTAGRAM_APP_CLIENT_SECRET="")
    def test_oauth_config_unconfigured_raises(self):
        with pytest.raises(NotImplementedError, match="Instagram app not configured"):
            OauthIntegration.oauth_config_for_kind("instagram")

    def test_the_instagram_grant_is_separate_from_the_meta_ads_one(self):
        # Both ride the same Meta app, but an ads grant carries none of the Instagram scopes,
        # so pointing the Instagram source at a meta-ads integration must not be possible.
        integration = Integration.objects.create(team=self.team, kind="meta-ads", integration_id="1")

        with pytest.raises(Exception, match="wrong 'kind'"):
            InstagramIntegration(integration)

    @patch("posthog.models.integration.meta.requests.post")
    def test_refresh_exchanges_the_long_lived_token_rather_than_a_refresh_token(self, mock_post):
        # Meta issues no refresh token: the current access token is swapped for a fresh one.
        integration = Integration.objects.create(
            team=self.team,
            kind="instagram",
            integration_id="fb-user-1",
            config={"expires_in": 100, "refreshed_at": int(time.time()) - 90},
            sensitive_config={"access_token": "old-token"},
        )
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "new-token", "expires_in": 5184000}

        InstagramIntegration(integration).refresh_access_token()

        sent = mock_post.call_args.kwargs["data"]
        assert sent["grant_type"] == "fb_exchange_token"
        assert sent["fb_exchange_token"] == "old-token"
        assert sent["client_id"] == "instagram-client-id"
        integration.refresh_from_db()
        assert integration.sensitive_config["access_token"] == "new-token"
        assert integration.errors == ""


@override_settings(META_ADS_APP_CLIENT_ID="meta-client-id", META_ADS_APP_CLIENT_SECRET="meta-client-secret")
class TestFacebookPagesIntegrationModel(BaseTest):
    def test_oauth_config_reuses_the_meta_app_with_the_page_scopes(self):
        config = OauthIntegration.oauth_config_for_kind("facebook-pages")

        assert config.authorize_url == "https://www.facebook.com/v25.0/dialog/oauth"
        assert config.token_url == "https://graph.facebook.com/v25.0/oauth/access_token"
        assert config.token_info_url == "https://graph.facebook.com/v25.0/me"
        assert config.client_id == "meta-client-id"
        assert config.client_secret == "meta-client-secret"
        assert config.scope.split(" ") == [
            "pages_show_list",
            "pages_read_engagement",
            "pages_read_user_content",
            "read_insights",
        ]
        assert config.id_path == "id"
        assert config.name_path == "name"

    def test_the_ads_grant_stays_scoped_to_ads(self):
        # A shared app, but separate consent screens: connecting Meta Ads must not ask for Pages access.
        assert OauthIntegration.oauth_config_for_kind("meta-ads").scope == "ads_read"

    @override_settings(META_ADS_APP_CLIENT_ID="", META_ADS_APP_CLIENT_SECRET="")
    def test_oauth_config_unconfigured_raises(self):
        with pytest.raises(NotImplementedError, match="Facebook Pages app not configured"):
            OauthIntegration.oauth_config_for_kind("facebook-pages")

    @patch("posthog.models.integration.meta.requests.post")
    def test_refresh_re_mints_the_long_lived_token(self, mock_post):
        # Meta issues no refresh token, so the token is re-minted with `fb_exchange_token`.
        integration = Integration.objects.create(
            team=self.team,
            kind="facebook-pages",
            integration_id="me_1",
            config={"expires_in": 100, "refreshed_at": int(time.time()) - 100},
            sensitive_config={"access_token": "old-token"},
        )
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "new-token", "expires_in": 5184000}

        FacebookPagesIntegration(integration).refresh_access_token()

        assert mock_post.call_args.kwargs["data"]["grant_type"] == "fb_exchange_token"
        assert mock_post.call_args.kwargs["data"]["client_id"] == "meta-client-id"
        integration.refresh_from_db()
        assert integration.sensitive_config["access_token"] == "new-token"

    def test_an_integration_of_another_kind_is_rejected(self):
        integration = Integration.objects.create(team=self.team, kind="meta-ads", integration_id="ads_1")

        with pytest.raises(Exception, match="FacebookPagesIntegration init called with Integration with wrong 'kind'"):
            FacebookPagesIntegration(integration)
