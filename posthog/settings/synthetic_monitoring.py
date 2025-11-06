import json

from posthog.settings.utils import get_from_env

# Lambda URLs for synthetic monitoring checks per region
# Expected format: {"us-east-2": "https://...", "ap-northeast-2": "https://...", ...}
SYNTHETIC_MONITORING_LAMBDA_URLS = json.loads(get_from_env("SYNTHETIC_MONITORING_LAMBDA_URLS", "{}"))
