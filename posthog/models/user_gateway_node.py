from posthog.models.user import User


def gateway_user_node(user: User) -> str:
    """The value the ai-gateway attributes a person's spend to.

    One definition for every writer of that node: the spend-limit endpoint that
    configures a per-person budget, the task runner that pins the node into a
    run's scoped token, and the desktop app that asserts it as a header. A
    disagreement between any two of them writes a budget that nothing debits, so
    they all read this.
    """
    return user.distinct_id or f"user_{user.id}"
