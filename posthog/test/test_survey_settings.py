import pytest

from django.core.exceptions import ImproperlyConfigured

from posthog.settings.surveys import validate_surveys_public_url


@pytest.mark.parametrize("cloud_deployment", ["US", "EU"])
def test_cloud_survey_origin_rejects_posthog_com_cookie_domain(cloud_deployment: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="cookie domain"):
        validate_surveys_public_url("https://surveys.posthog.com", cloud_deployment)


@pytest.mark.parametrize("cloud_deployment", ["US", "EU"])
def test_cloud_survey_origin_accepts_separate_cookie_domain(cloud_deployment: str) -> None:
    assert (
        validate_surveys_public_url("https://surveys.posthogusercontent.com/", cloud_deployment)
        == "https://surveys.posthogusercontent.com"
    )
