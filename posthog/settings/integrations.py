from posthog.settings.utils import get_from_env, get_list, str_to_bool

# Integration service. Both unset (the default) means credential reads fall back to the
# local environment; see posthog/integration_secrets/client.py for the contract.
INTEGRATION_SERVICE_URL = get_from_env("INTEGRATION_SERVICE_URL", "")
# Comma-separated `new,old`, newest first. Per deployment, not fleet-wide.
INTEGRATION_SERVICE_JWT_SECRET = get_from_env("INTEGRATION_SERVICE_JWT_SECRET", "")

HUBSPOT_APP_CLIENT_ID = get_from_env("HUBSPOT_APP_CLIENT_ID", "")
HUBSPOT_APP_CLIENT_SECRET = get_from_env("HUBSPOT_APP_CLIENT_SECRET", "")

SNAPCHAT_APP_CLIENT_ID = get_from_env("SNAPCHAT_APP_CLIENT_ID", "")
SNAPCHAT_APP_CLIENT_SECRET = get_from_env("SNAPCHAT_APP_CLIENT_SECRET", "")

INTERCOM_APP_CLIENT_ID = get_from_env("INTERCOM_APP_CLIENT_ID", "")
INTERCOM_APP_CLIENT_SECRET = get_from_env("INTERCOM_APP_CLIENT_SECRET", "")

# Resend registers a confidential OAuth client (token_endpoint_auth_method=client_secret_post) via
# its dynamic client registration API (POST https://api.resend.com/oauth/register). Empty defaults
# keep the app importable and the OAuth auth method dormant until the client is provisioned.
RESEND_APP_CLIENT_ID = get_from_env("RESEND_APP_CLIENT_ID", "")
RESEND_APP_CLIENT_SECRET = get_from_env("RESEND_APP_CLIENT_SECRET", "")

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

GOOGLE_CALENDAR_APP_CLIENT_ID = get_from_env("GOOGLE_CALENDAR_APP_CLIENT_ID", "")
GOOGLE_CALENDAR_APP_CLIENT_SECRET = get_from_env("GOOGLE_CALENDAR_APP_CLIENT_SECRET", "")

# Registered in the Google Cloud console with the YouTube Analytics API and the YouTube Data API
# enabled. Empty defaults keep the app importable and the connector dormant until the client exists.
YOUTUBE_ANALYTICS_APP_CLIENT_ID = get_from_env("YOUTUBE_ANALYTICS_APP_CLIENT_ID", "")
YOUTUBE_ANALYTICS_APP_CLIENT_SECRET = get_from_env("YOUTUBE_ANALYTICS_APP_CLIENT_SECRET", "")

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

# Stamphog runs as its own dedicated GitHub App (separate identity from the core
# GITHUB_APP_* above), so it carries its own App id, JWT-signing private key, and
# webhook secret. Empty defaults keep the app importable when Stamphog is unconfigured.
STAMPHOG_GITHUB_APP_ID = get_from_env("STAMPHOG_GITHUB_APP_ID", "")
STAMPHOG_GITHUB_APP_PRIVATE_KEY = get_from_env("STAMPHOG_GITHUB_APP_PRIVATE_KEY", "")
STAMPHOG_GITHUB_APP_WEBHOOK_SECRET = get_from_env("STAMPHOG_GITHUB_APP_WEBHOOK_SECRET", "")
# OAuth client id/secret for the Stamphog App's user-to-server authorization flow (enabled via
# "Request user authorization during installation"). Used to exchange the post-install `code` for a
# user access token and prove the caller actually owns the installation before its repos are bound to
# their team. Separate from the JWT-signing private key above. Empty until the App is provisioned, in
# which case installation binding fails closed.
STAMPHOG_GITHUB_APP_CLIENT_ID = get_from_env("STAMPHOG_GITHUB_APP_CLIENT_ID", "")
STAMPHOG_GITHUB_APP_CLIENT_SECRET = get_from_env("STAMPHOG_GITHUB_APP_CLIENT_SECRET", "")
# URL-friendly App name in github.com/apps/<slug>; the install URL is built from it. Empty until
# the App is provisioned, in which case the install-info endpoint returns a blank install URL.
STAMPHOG_GITHUB_APP_SLUG = get_from_env("STAMPHOG_GITHUB_APP_SLUG", "")
# Extra outbound domains the review sandbox may reach, on top of the built-in allowlist (GitHub,
# PyPI, the LLM gateway host, the PostHog capture host). Comma-separated; an ops escape hatch for
# when a legitimate dependency host is missing — never a way to open the sandbox wide.
STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS = get_list(get_from_env("STAMPHOG_SANDBOX_EXTRA_EGRESS_DOMAINS", ""))
# Installation id of the GitHub App on the PostHog/community-skills repo, used by the in-product
# "Publish to community" flow to open skill PRs. Empty (the default) disables publishing → the
# endpoint returns 503 and the UI falls back to the manual-PR path.
COMMUNITY_SKILLS_GITHUB_INSTALLATION_ID = get_from_env("COMMUNITY_SKILLS_GITHUB_INSTALLATION_ID", "")
# Bare repo name (no owner prefix) — the owner is the App installation's account. Defaults to the
# PostHog/community-skills repo. Publish-only: the hourly catalog sync reads its registry from the
# repo pinned in community_skill_sync.py, so pointing this elsewhere sends pull requests to a repo the
# sync does not read back.
COMMUNITY_SKILLS_GITHUB_REPO = get_from_env("COMMUNITY_SKILLS_GITHUB_REPO", "community-skills")

META_ADS_APP_CLIENT_ID = get_from_env("META_ADS_APP_CLIENT_ID", "")
META_ADS_APP_CLIENT_SECRET = get_from_env("META_ADS_APP_CLIENT_SECRET", "")

# Instagram professional accounts authorize through Facebook Login, so these may point at the
# same Meta app as META_ADS_APP_* — the two grants differ only in the scopes they request.
INSTAGRAM_APP_CLIENT_ID = get_from_env("INSTAGRAM_APP_CLIENT_ID", "")
INSTAGRAM_APP_CLIENT_SECRET = get_from_env("INSTAGRAM_APP_CLIENT_SECRET", "")

BING_ADS_CLIENT_ID = get_from_env("BING_ADS_CLIENT_ID", "")
BING_ADS_CLIENT_SECRET = get_from_env("BING_ADS_CLIENT_SECRET", "")
BING_ADS_CLIENT_ID_FALLBACK = get_from_env("BING_ADS_CLIENT_ID_FALLBACK", "")
BING_ADS_CLIENT_SECRET_FALLBACK = get_from_env("BING_ADS_CLIENT_SECRET_FALLBACK", "")
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
# - STRIPE_POSTHOG_OAUTH_CLIENT_ID: Client ID of the PostHog OAuthApplication the provisioning
#   orchestrator authenticates as. Tokens on this application may mint deep-link login sessions.
# - STRIPE_MARKETPLACE_OAUTH_CLIENT_ID: Client ID of a separate PostHog OAuthApplication for the
#   marketplace app's own token. That token is written into the customer's Stripe Secret Store at
#   account scope, so every member of their Stripe account can read it. It must not share an
#   application with the orchestrator, because the provisioning namespace authorizes on application
#   identity alone. Until this is set the two share one application and marketplace tokens can reach
#   the provisioning endpoints.
# - STRIPE_SIGNING_SECRET: Used to verify the authenticity of incoming webhook/agentic provisioning requests from Stripe
STRIPE_APP_CLIENT_ID = get_from_env("STRIPE_APP_CLIENT_ID", "")
STRIPE_APP_OVERRIDE_AUTHORIZE_URL = get_from_env("STRIPE_APP_OVERRIDE_AUTHORIZE_URL", "")
STRIPE_APP_SECRET_KEY = get_from_env("STRIPE_APP_SECRET_KEY", "")
STRIPE_POSTHOG_OAUTH_CLIENT_ID = get_from_env("STRIPE_POSTHOG_OAUTH_CLIENT_ID", "")
STRIPE_MARKETPLACE_OAUTH_CLIENT_ID = get_from_env("STRIPE_MARKETPLACE_OAUTH_CLIENT_ID", "")
STRIPE_SIGNING_SECRET = get_from_env("STRIPE_SIGNING_SECRET", "")

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

# PostHog connect — lets a user connect (via the target's OAuth consent flow) to another PostHog
# project to drive its APIs, e.g. dispatching a Task that must run in that project (including one in
# another region, to reach region-resident data). The target may be in a different region OR the
# same one as the connecting project — same-region is just "target region == your region". The
# connecting side is the OAuth *client*: it redirects to the target region's /oauth/authorize and
# exchanges the code against its /oauth/token, so it needs that region's registered app credentials
# plus its public base URL. One entry per region a user may connect TO (your own included). Empty
# defaults keep the app importable until the OAuthApplications are provisioned in each region, in
# which case the connect flow fails closed for the unconfigured region.
POSTHOG_CONNECT_OAUTH_CLIENT_ID_US = get_from_env("POSTHOG_CONNECT_OAUTH_CLIENT_ID_US", "")
POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_US = get_from_env("POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_US", "")
POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU = get_from_env("POSTHOG_CONNECT_OAUTH_CLIENT_ID_EU", "")
POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU = get_from_env("POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_EU", "")
POSTHOG_CONNECT_OAUTH_CLIENT_ID_DEV = get_from_env("POSTHOG_CONNECT_OAUTH_CLIENT_ID_DEV", "")
POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_DEV = get_from_env("POSTHOG_CONNECT_OAUTH_CLIENT_SECRET_DEV", "")
# Public base URL of each target cell's OAuth server. DEV points at the local instance so the flow
# is exercisable end to end against a single dev stack; override via env for a custom dev host.
POSTHOG_CONNECT_BASE_URL_US = get_from_env("POSTHOG_CONNECT_BASE_URL_US", "https://us.posthog.com")
POSTHOG_CONNECT_BASE_URL_EU = get_from_env("POSTHOG_CONNECT_BASE_URL_EU", "https://eu.posthog.com")
POSTHOG_CONNECT_BASE_URL_DEV = get_from_env("POSTHOG_CONNECT_BASE_URL_DEV", "http://localhost:8000")

# Legacy OAuth client credentials kept alive during an app or secret rotation.
# Refreshes fall back to these when the primary credentials fail, so tokens issued
# by a since-migrated app keep working until users reconnect.
OAUTH_CLIENT_FALLBACKS: dict[str, dict[str, str]] = {
    "bing-ads": {
        "client_id": BING_ADS_CLIENT_ID_FALLBACK,
        "client_secret": BING_ADS_CLIENT_SECRET_FALLBACK,
    },
}
