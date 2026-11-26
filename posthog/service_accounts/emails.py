from uuid import UUID

# Nothing receives mail at this domain. A service account needs an address only because `User.email` is
# required and unique.
SERVICE_ACCOUNT_EMAIL_DOMAIN = "service.posthog.com"


def generated_service_account_email(user_uuid: UUID | str) -> str:
    return f"user-{user_uuid}@{SERVICE_ACCOUNT_EMAIL_DOMAIN}"


def is_generated_service_account_email(email: str) -> bool:
    return email.strip().lower().endswith(f"@{SERVICE_ACCOUNT_EMAIL_DOMAIN}")
