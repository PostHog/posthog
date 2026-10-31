import pytest

from django.test import Client, override_settings

TEAM_ID = "ABCDE12345"
FINGERPRINT = "AA:BB:CC:DD"


@override_settings(MOBILE_APP_APPLE_TEAM_ID=TEAM_ID, MOBILE_APP_ANDROID_CERT_FINGERPRINTS=[FINGERPRINT])
def test_apple_app_site_association_is_served_without_login_or_redirect():
    response = Client().get("/.well-known/apple-app-site-association")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    [detail] = response.json()["applinks"]["details"]
    assert f"{TEAM_ID}.com.posthog.code.mobile" in detail["appIDs"]
    assert detail["components"] == [{"/": "/project/*/inbox/reports/*"}]


@override_settings(MOBILE_APP_APPLE_TEAM_ID=TEAM_ID, MOBILE_APP_ANDROID_CERT_FINGERPRINTS=[FINGERPRINT])
def test_android_asset_links_are_served_without_login_or_redirect():
    response = Client().get("/.well-known/assetlinks.json")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    statements = {statement["target"]["package_name"]: statement for statement in response.json()}
    production = statements["com.posthog.mobile"]
    assert production["relation"] == ["delegate_permission/common.handle_all_urls"]
    assert production["target"]["sha256_cert_fingerprints"] == [FINGERPRINT]


@pytest.mark.parametrize("path", ["/.well-known/apple-app-site-association", "/.well-known/assetlinks.json"])
@override_settings(MOBILE_APP_APPLE_TEAM_ID="", MOBILE_APP_ANDROID_CERT_FINGERPRINTS=[])
def test_association_files_are_absent_where_the_app_is_not_configured(path):
    # Self-hosted instances must not claim the PostHog mobile app for their domain.
    assert Client().get(path).status_code == 404
