from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_from_env, get_list

# The security hub owns access rules; this deployment pulls them.
# Unset → no sync, and decisions run against an empty rule set.
SECURITY_HUB_URL: str = get_from_env("SECURITY_HUB_URL", "")

# This deployment's region as the hub knows it ("us", "eu"). Tokens in both directions
# carry it, so a token for one region can't be replayed against another.
SECURITY_HUB_REGION: str = get_from_env("SECURITY_HUB_REGION", "dev" if DEBUG or TEST else "")

# Verifies the tokens the hub signs for this region's /api/security/ routes.
# Comma-separated, newest first. Empty in prod until provisioned, so the routes refuse
# every call.
SECURITY_HUB_INBOUND_JWT_SECRETS: list[str] = get_list(
    get_from_env("SECURITY_HUB_INBOUND_JWT_SECRETS", "local-dev-security-hub-inbound" if DEBUG or TEST else "")
)

# Signs this region's snapshot requests to the hub. Comma-separated, newest first.
SECURITY_HUB_OUTBOUND_JWT_SECRETS: list[str] = get_list(
    get_from_env("SECURITY_HUB_OUTBOUND_JWT_SECRETS", "local-dev-security-hub-outbound" if DEBUG or TEST else "")
)

# Surfaces where a matching block rule refuses the request: "signup", "ai_gateway", "app".
# Comma-separated. A surface left out only records what a block rule would refuse, so an
# unset value keeps every surface in shadow mode. Remove a surface to stop refusing there.
SECURITY_ACCESS_ENFORCED_SURFACES: list[str] = get_list(get_from_env("SECURITY_ACCESS_ENFORCED_SURFACES", ""))
