import os

from posthog.settings.utils import get_list

# Cloud-only. Self-hosted instances leave these empty so they do not claim the PostHog mobile app.
MOBILE_APP_APPLE_TEAM_ID = os.getenv("MOBILE_APP_APPLE_TEAM_ID", "")
# Comma-separated SHA-256 signing certificate fingerprints, for example the Play App Signing key.
MOBILE_APP_ANDROID_CERT_FINGERPRINTS = get_list(os.getenv("MOBILE_APP_ANDROID_CERT_FINGERPRINTS", ""))
