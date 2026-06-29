from posthog.settings.utils import get_from_env, str_to_bool

HUBSPOT_APP_CLIENT_ID = get_from_env("HUBSPOT_APP_CLIENT_ID", "")
HUBSPOT_APP_CLIENT_SECRET = get_from_env("HUBSPOT_APP_CLIENT_SECRET", "")

SNAPCHAT_APP_CLIENT_ID = get_from_env("SNAPCHAT_APP_CLIENT_ID", "")
SNAPCHAT_APP_CLIENT_SECRET = get_from_env("SNAPCHAT_APP_CLIENT_SECRET", "")

INTERCOM_APP_CLIENT_ID = get_from_env("INTERCOM_APP_CLIENT_ID", "")
INTERCOM_APP_CLIENT_SECRET = get_from_env("INTERCOM_APP_CLIENT_SECRET", "")

SALESFORCE_CONSUMER_KEY = get_from_env("SALESFORCE_CONSUMER_KEY", "")
SALESFORCE_CONSUMER_SECRET = get_from_env("SALESFORCE_CONSUMER_SECRET", "")

LINKEDIN_APP_CLIENT_ID = get_from_env("LINKEDIN_APP_CLIENT_ID", "")
LINKEDIN_APP_CLIENT_SECRET = get_from_env("LINKEDIN_APP_CLIENT_SECRET", "")

GOOGLE_ADS_APP_CLIENT_ID = get_from_env("GOOGLE_ADS_APP_CLIENT_ID", "")
GOOGLE_ADS_APP_CLIENT_SECRET = get_from_env("GOOGLE_ADS_APP_CLIENT_SECRET", "")
GOOGLE_ADS_DEVELOPER_TOKEN = get_from_env("GOOGLE_ADS_DEVELOPER_TOKEN", "")

GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID = get_from_env("GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID", "")
GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET = get_from_env("GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET", "")

GOOGLE_ANALYTICS_APP_CLIENT_ID = get_from_env("GOOGLE_ANALYTICS_APP_CLIENT_ID", "")
GOOGLE_ANALYTICS_APP_CLIENT_SECRET = get_from_env("GOOGLE_ANALYTICS_APP_CLIENT_SECRET", "")

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
# - STRIPE_APP_SECRET_KEY: API secret key used for HTTP Basic auth during live token exchange/refresh
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

# ElevenLabs (Max hands-free mode)
# STT goes browser ↔ ElevenLabs over a single-use Scribe WebSocket token (backend just mints).
# TTS goes browser → PostHog → ElevenLabs → audio stream (backend proxies the key to ElevenLabs).
ELEVENLABS_API_KEY = get_from_env("ELEVENLABS_API_KEY", "")
ELEVENLABS_API_BASE_URL = get_from_env("ELEVENLABS_API_BASE_URL", "https://api.elevenlabs.io")
# Rachel is ElevenLabs' default voice — neutral, clear at gym pace. Override if you want a
# different feel without redeploying.
ELEVENLABS_VOICE_ID = get_from_env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
# Turbo v2.5 has ~300ms TTFB latency, sits in the free tier, and sounds clean enough for
# gym-pace narration. Flash v2.5 is marginally faster but requires Creator ($22/mo) or above
# on the ElevenLabs side, so devs running on free quota hit a 402 from the TTS proxy.
# Override at the env level if you're on a paid tier and want the extra polish.
ELEVENLABS_TTS_MODEL_ID = get_from_env("ELEVENLABS_TTS_MODEL_ID", "eleven_turbo_v2_5")

# PandaDoc (for legal documents: BAA/DPA). One template per document variant.
# Each call needs the matching template id, so we keep them as separate env vars —
# rotating one (e.g., when Legal updates the DPA copy) doesn't touch the others.
PANDADOC_API_BASE_URL = get_from_env("PANDADOC_API_BASE_URL", "https://api.pandadoc.com")
PANDADOC_API_KEY = get_from_env("PANDADOC_API_KEY", "")
PANDADOC_WEBHOOK_SECRET = get_from_env("PANDADOC_WEBHOOK_SECRET", "")
PANDADOC_BAA_TEMPLATE_ID = get_from_env("PANDADOC_BAA_TEMPLATE_ID", "")
PANDADOC_DPA_TEMPLATE_ID = get_from_env("PANDADOC_DPA_TEMPLATE_ID", "")

# Unlayer (server-side email design → HTML rendering for message templates)
UNLAYER_API_KEY = get_from_env("UNLAYER_API_KEY", "")
UNLAYER_API_BASE_URL = get_from_env("UNLAYER_API_BASE_URL", "https://api.unlayer.com")

HEATMAP_BROWSERLESS_URL = get_from_env("HEATMAP_BROWSERLESS_URL", "")
HEATMAP_BROWSERLESS_TOKEN = get_from_env("HEATMAP_BROWSERLESS_TOKEN", "")
# Browserless /screenshot session cap (ms); must stay under the plan's max-timeout.
HEATMAP_BROWSERLESS_TIMEOUT_MS = get_from_env("HEATMAP_BROWSERLESS_TIMEOUT_MS", 180000, type_cast=int)
HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS = get_from_env("HEATMAP_BROWSERLESS_CONNECT_TIMEOUT_MS", 30000, type_cast=int)
HEATMAP_BROWSERLESS_BLOCK_ADS = get_from_env("HEATMAP_BROWSERLESS_BLOCK_ADS", False, type_cast=str_to_bool)
