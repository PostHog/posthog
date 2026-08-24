from posthog.models.user import User


def gateway_user_node(user: User) -> str:
    return user.distinct_id or f"user_{user.id}"
