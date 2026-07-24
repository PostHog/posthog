from posthog.models import ProjectSecretAPIKey, Team, User
from posthog.models.utils import generate_random_token_secret, hash_key_value, mask_key_value


def create_project_secret_api_key(
    team: Team,
    created_by: User | None = None,
    label: str = "Test key",
    scopes: list[str] | None = None,
) -> tuple[ProjectSecretAPIKey, str]:
    """Create a PSAK the way the API does (hashed secure_value, masked display value) and
    return it along with the plaintext token, which is never stored."""
    value = generate_random_token_secret()
    key = ProjectSecretAPIKey.objects.create(
        team=team,
        label=label,
        secure_value=hash_key_value(value),
        mask_value=mask_key_value(value),
        created_by=created_by,
        scopes=scopes or ["feature_flag:read"],
    )
    return key, value
