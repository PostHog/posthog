import os
import json

# Lambda URLs for synthetic monitoring checks per region
# Expected format: {"us-east-2": "https://...", "ap-northeast-2": "https://...", ...}
# Using os.getenv directly since .env might not be loaded when settings are imported
_lambda_urls_env = os.getenv("SYNTHETIC_MONITORING_LAMBDA_URLS", "{}")
try:
    SYNTHETIC_MONITORING_LAMBDA_URLS = json.loads(_lambda_urls_env) if _lambda_urls_env else {}
except json.JSONDecodeError:
    SYNTHETIC_MONITORING_LAMBDA_URLS = {}
