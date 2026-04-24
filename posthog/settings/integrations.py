from posthog.settings.utils import get_from_env, str_to_bool

HUBSPOT_APP_CLIENT_ID = get_from_env("HUBSPOT_APP_CLIENT_ID", "")
HUBSPOT_APP_CLIENT_SECRET = get_from_env("HUBSPOT_APP_CLIENT_SECRET", "")

SNAPCHAT_APP_CLIENT_ID = get_from_env("SNAPCHAT_APP_CLIENT_ID", "")
SNAPCHAT_APP_CLIENT_SECRET = get_from_env("SNAPCHAT_APP_CLIENT_SECRET", "")

INTERCOM_APP_CLIENT_ID = get_from_env("INTERCOM_APP_CLIENT_ID", "")
INTERCOM_APP_CLIENT_SECRET = get_from_env("INTERCOM_APP_CLIENT_SECRET", "")

SLACK_POSTHOG_CODE_CLIENT_ID = get_from_env("SLACK_POSTHOG_CODE_CLIENT_ID", get_from_env("SLACK_TWIG_CLIENT_ID", ""))
SLACK_POSTHOG_CODE_CLIENT_SECRET = get_from_env(
    "SLACK_POSTHOG_CODE_CLIENT_SECRET", get_from_env("SLACK_TWIG_CLIENT_SECRET", "")
)
SLACK_POSTHOG_CODE_SIGNING_SECRET = get_from_env(
    "SLACK_POSTHOG_CODE_SIGNING_SECRET", get_from_env("SLACK_TWIG_SIGNING_SECRET", "")
)

SALESFORCE_CONSUMER_KEY = get_from_env("SALESFORCE_CONSUMER_KEY", "")
SALESFORCE_CONSUMER_SECRET = get_from_env("SALESFORCE_CONSUMER_SECRET", "")

LINKEDIN_APP_CLIENT_ID = get_from_env("LINKEDIN_APP_CLIENT_ID", "")
LINKEDIN_APP_CLIENT_SECRET = get_from_env("LINKEDIN_APP_CLIENT_SECRET", "")

GOOGLE_ADS_APP_CLIENT_ID = get_from_env("GOOGLE_ADS_APP_CLIENT_ID", "")
GOOGLE_ADS_APP_CLIENT_SECRET = get_from_env("GOOGLE_ADS_APP_CLIENT_SECRET", "")
GOOGLE_ADS_DEVELOPER_TOKEN = get_from_env("GOOGLE_ADS_DEVELOPER_TOKEN", "")

SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = get_from_env("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY", "")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = get_from_env("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET", "")

LINEAR_APP_CLIENT_ID = get_from_env("LINEAR_APP_CLIENT_ID", "")
LINEAR_APP_CLIENT_SECRET = get_from_env("LINEAR_APP_CLIENT_SECRET", "")

GITHUB_APP_CLIENT_ID = get_from_env("GITHUB_APP_CLIENT_ID", "")
GITHUB_APP_PRIVATE_KEY = get_from_env("GITHUB_APP_PRIVATE_KEY", "")
# OAuth *secret* for the same GitHub App as above - generated in the App's settings
# when "Request user authorization during installation" is enabled.
# Used with GITHUB_APP_CLIENT_ID to exchange an authorization code for a user access token,
# which is separate from the private key used for App-as-App JWT signing.
GITHUB_APP_CLIENT_SECRET = get_from_env("GITHUB_APP_CLIENT_SECRET", "")

ZENDESK_ADMIN_EMAIL = get_from_env("ZENDESK_ADMIN_EMAIL", "")
ZENDESK_API_TOKEN = get_from_env("ZENDESK_API_TOKEN", "")
ZENDESK_SUBDOMAIN = get_from_env("ZENDESK_SUBDOMAIN", "posthoghelp")

META_ADS_APP_CLIENT_ID = get_from_env("META_ADS_APP_CLIENT_ID", "")
META_ADS_APP_CLIENT_SECRET = get_from_env("META_ADS_APP_CLIENT_SECRET", "")

BING_ADS_CLIENT_ID = get_from_env("BING_ADS_CLIENT_ID", "")
BING_ADS_CLIENT_SECRET = get_from_env("BING_ADS_CLIENT_SECRET", "")
BING_ADS_DEVELOPER_TOKEN = get_from_env("BING_ADS_DEVELOPER_TOKEN", "")

REDDIT_ADS_CLIENT_ID = get_from_env("REDDIT_ADS_CLIENT_ID", "")
REDDIT_ADS_CLIENT_SECRET = get_from_env("REDDIT_ADS_CLIENT_SECRET", "")

PINTEREST_ADS_CLIENT_ID = get_from_env("PINTEREST_ADS_CLIENT_ID", "")
PINTEREST_ADS_CLIENT_SECRET = get_from_env("PINTEREST_ADS_CLIENT_SECRET", "")

TIKTOK_ADS_CLIENT_ID = get_from_env("TIKTOK_ADS_CLIENT_ID", "")
TIKTOK_ADS_CLIENT_SECRET = get_from_env("TIKTOK_ADS_CLIENT_SECRET", "")

CLICKUP_APP_CLIENT_ID = get_from_env("CLICKUP_APP_CLIENT_ID", "")
CLICKUP_APP_CLIENT_SECRET = get_from_env("CLICKUP_APP_CLIENT_SECRET", "")

ATLASSIAN_APP_CLIENT_ID = get_from_env("ATLASSIAN_APP_CLIENT_ID", "")
ATLASSIAN_APP_CLIENT_SECRET = get_from_env("ATLASSIAN_APP_CLIENT_SECRET", "")

# Stripe requires a more complex OAuth setup: we authenticate with Stripe, then exchange tokens
# with our internal OAuth system to allow the Stripe app to make API calls to users' PostHog instances.
# We also support their agentic provisioning protocol which requires us to check even more stuff
# - STRIPE_APP_CLIENT_ID: The app's public client ID, used in the OAuth authorize redirect URL
# - STRIPE_APP_OVERRIDE_AUTHORIZE_URL: Optional override for testing (e.g., with a channel link URL)
# - STRIPE_APP_SECRET_KEY: API secret key used for HTTP Basic auth during token exchange/refresh
# - STRIPE_POSTHOG_OAUTH_CLIENT_ID: Client ID of the PostHog OAuthApplication for Stripe to authenticate with PostHog APIs
# - STRIPE_SIGNING_SECRET: Used to verify the authenticity of incoming webhook/agentic provisioning requests from Stripe
STRIPE_APP_CLIENT_ID = get_from_env("STRIPE_APP_CLIENT_ID", "")
STRIPE_APP_OVERRIDE_AUTHORIZE_URL = get_from_env("STRIPE_APP_OVERRIDE_AUTHORIZE_URL", "")
STRIPE_APP_SECRET_KEY = get_from_env("STRIPE_APP_SECRET_KEY", "")
STRIPE_POSTHOG_OAUTH_CLIENT_ID = get_from_env("STRIPE_POSTHOG_OAUTH_CLIENT_ID", "")
STRIPE_SIGNING_SECRET = get_from_env("STRIPE_SIGNING_SECRET", "")
STRIPE_ORCHESTRATOR_CALLBACK_URL = get_from_env("STRIPE_ORCHESTRATOR_CALLBACK_URL", "")

# WorkOS Radar (bot/fraud detection for auth flows)
WORKOS_RADAR_API_KEY = get_from_env("WORKOS_RADAR_API_KEY", "")
WORKOS_RADAR_ENABLED = get_from_env("WORKOS_RADAR_ENABLED", False, type_cast=str_to_bool)

# Cloudflare Turnstile (challenge verification for Radar "challenge" verdict)
CLOUDFLARE_TURNSTILE_SECRET_KEY = get_from_env("CLOUDFLARE_TURNSTILE_SECRET_KEY", "")
CLOUDFLARE_TURNSTILE_SITE_KEY = get_from_env("CLOUDFLARE_TURNSTILE_SITE_KEY", "")

# Recall.ai (for desktop recordings product)
RECALL_AI_API_KEY = get_from_env("RECALL_AI_API_KEY", "")
RECALL_AI_API_URL = get_from_env("RECALL_AI_API_URL", "https://us-west-2.recall.ai")

# PandaDoc (for legal documents: BAA/DPA). One template per document variant.
# Each call needs the matching template id, so we keep them as separate env vars —
# rotating one (e.g., when Legal updates the DPA copy) doesn't touch the others.
PANDADOC_API_BASE_URL = get_from_env("PANDADOC_API_BASE_URL", "https://api.pandadoc.com")
PANDADOC_API_KEY = get_from_env("PANDADOC_API_KEY", "")
PANDADOC_WEBHOOK_SECRET = get_from_env("PANDADOC_WEBHOOK_SECRET", "")
PANDADOC_BAA_TEMPLATE_ID = get_from_env("PANDADOC_BAA_TEMPLATE_ID", "")
PANDADOC_DPA_TEMPLATE_ID = get_from_env("PANDADOC_DPA_TEMPLATE_ID", "")

# Slack incoming-webhook URL for internal legal-document notifications. The URL
# is bound to a single channel at creation time in Slack's app admin, so there's
# no channel to configure and no bot token to manage. Separate from the per-org
# Slack integration used in products/slack_app.
SLACK_LEGAL_DOCUMENTS_WEBHOOK_URL = get_from_env("SLACK_LEGAL_DOCUMENTS_WEBHOOK_URL", "")
