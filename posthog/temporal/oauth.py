from datetime import timedelta

from django.utils import timezone

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token
from posthog.utils import get_instance_region

ARRAY_APP_CLIENT_ID_US = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W"
ARRAY_APP_CLIENT_ID_EU = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9"
ARRAY_APP_CLIENT_ID_DEV = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"


def get_array_app() -> OAuthApplication:
    region = get_instance_region()
    if region == "EU":
        client_id = ARRAY_APP_CLIENT_ID_EU
    elif region == "US":
        client_id = ARRAY_APP_CLIENT_ID_US
    else:
        client_id = ARRAY_APP_CLIENT_ID_DEV

    try:
        return OAuthApplication.objects.get(client_id=client_id)
    except OAuthApplication.DoesNotExist as err:
        raise RuntimeError(f"Array app not found for region {region} (client_id={client_id})") from err


def get_default_scopes() -> list[str]:
    return [
        "user:read",
        "organization:read",
        "project:read",
        "task:write",
        "llm_gateway:read",
    ]


def create_oauth_access_token_for_user(user, team_id: int) -> str:
    scopes = get_default_scopes()
    app = get_array_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        user=user,
        application=app,
        token=token_value,
        expires=timezone.now() + timedelta(hours=6),
        scope=" ".join(scopes),
        scoped_teams=[team_id],
    )

    return token_value
