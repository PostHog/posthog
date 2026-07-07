import os

from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool

# ARN of the PostHog-owned IAM role the batch import worker runs as. Customers grant this
# role access to their S3 buckets via a cross-account trust policy, so it must stay stable.
MANAGED_MIGRATIONS_IMPORT_ROLE_ARN: str = os.getenv("MANAGED_MIGRATIONS_IMPORT_ROLE_ARN", "")

# Requires the Django pods to be allowed to assume MANAGED_MIGRATIONS_IMPORT_ROLE_ARN,
# so it stays off until that grant exists in the deployment.
MANAGED_MIGRATIONS_VALIDATE_ROLE_ON_CREATE: bool = get_from_env(
    "MANAGED_MIGRATIONS_VALIDATE_ROLE_ON_CREATE", False, type_cast=str_to_bool
)
