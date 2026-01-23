# Vercel SSO + ngrok Local Development Setup

This guide documents the complete setup process for testing Vercel SSO integration locally using ngrok for HTTPS.

## Prerequisites

- ngrok installed and authenticated: `brew install --cask ngrok`
- 1Password CLI installed (if using 1Password option): `brew install --cask 1password-cli`

## Step 1: Configure ngrok Tunnels

Follow the [PostHog ngrok setup guide](https://posthog.com/handbook/engineering/setup-ssl-locally) to configure ngrok.

**Quick version:**

1. Find your ngrok config location: `ngrok config check --log=stdout`
2. Edit the config file to add tunnels for Django (port 8000) and webpack (port 8234)
3. Start only the Django tunnel: `ngrok start django`

This will give you an HTTPS URL for port 8000, e.g., `https://abc123.ngrok-free.dev`

**Note**: You only need the Django tunnel. Vite will serve assets locally on port 8234, and the Django tunnel will proxy requests to it.

## Step 2: Configure PostHog Environment Variables

Create a `.env.vercel` file in the PostHog root directory with your ngrok URL (copy from `.env.vercel.example` in this directory)

```bash
# Enable HTTPS mode for local development
LOCAL_HTTPS=1
DEBUG=1

# ngrok tunnel URLs for HTTPS local development (update with your ngrok URL)
SITE_URL=https://your-ngrok-tunnel.ngrok-free.dev
JS_URL=https://your-ngrok-tunnel.ngrok-free.dev
WEBPACK_HOT_RELOAD_HOST=0.0.0.0

# Vercel integration credentials (automatically loaded from 1Password)
VERCEL_CLIENT_INTEGRATION_ID="op://General/Vercel Client Integration Secret/client id"
VERCEL_CLIENT_INTEGRATION_SECRET="op://General/Vercel Client Integration Secret/client secret"
```

**Notes**:

- If you need to configure CORS for ngrok (e.g., for hot reload or asset loading), you can temporarily modify `frontend/vite.config.ts` to add your ngrok domain to the `cors.origin` array and `allowedHosts`. **Do not commit these changes** - they are for local development only.

## Step 3: Configure Vercel Integration Settings

In your Vercel integration settings:

1. **Configuration URL**: Set to your Django tunnel URL (port 8000)
   - Example: `https://abc123.ngrok-free.dev`

2. **Redirect URL**: **Leave this field BLANK/EMPTY**
   - Vercel marketplace integrations don't need a redirect URL
   - Installation happens via API calls, not web redirects
   - SSO flow includes the return URL in the `url` query parameter

## Step 4: Start Development Servers

Run PostHog with 1Password to load the Vercel credentials:

```bash
op run --env-file=.env.vercel -- bin/start
```

This will:

1. Read your `.env.vercel` file
2. Fetch the Vercel credentials from 1Password
3. Start both Django and Vite dev servers with all environment variables loaded

## Architecture Notes

### Installation vs SSO Flows

Vercel marketplace integrations have two separate flows:

1. **Installation Flow** (API-based):
   - Endpoint: `/api/vercel/v1/installations/{id}`
   - Triggered by API calls from Vercel to PostHog
   - No user-facing web page
   - Creates the integration record in PostHog

2. **SSO Flow** (web-based):
   - Endpoint: `/login/vercel/`
   - Triggered when user clicks "Connect Account" in Vercel
   - Authenticates the user and links their PostHog account
   - Returns user back to Vercel using the `url` parameter

### Why No Redirect URL?

The "Redirect URL" field in Vercel integration settings is for OAuth-style integrations. PostHog's Vercel marketplace integration doesn't need it because:

- Installation happens via direct API calls
- SSO flow receives the return URL in the `url` query parameter from Vercel
- No web-based OAuth callback is needed

## Troubleshooting

### "This host is not allowed" from Vite

**Solution**: Add ngrok domains to `allowedHosts` in vite.config.ts (see Step 3)

### CORS errors when loading JavaScript assets

**Solution**: Add your ngrok domain to the `cors.origin` array in vite.config.ts (see Step 3)

### JWT validation failing with "Audience doesn't match"

**Solution**: Verify `VERCEL_CLIENT_INTEGRATION_ID` matches your Vercel integration's Client ID exactly

### Getting 400/404 errors during installation

**Solution**:

1. Check that Redirect URL is blank/empty in Vercel settings
2. Verify Configuration URL points to your Django ngrok tunnel (port 8000)
3. Check Django logs for detailed error messages

### Environment variables not loaded

**Solution**:

1. Verify you're authenticated with 1Password CLI: `op whoami`
2. Test credential loading: `op run --env-file=.env.vercel -- printenv | grep VERCEL`
3. Restart your Django server
4. Verify ngrok URL is set: Check that `JS_URL` and `NGROK_ORIGIN` in your `.env.vercel` match your ngrok tunnel URL

### 1Password shows "<concealed by 1Password>" in logs

This is normal! 1Password CLI conceals sensitive values in stdout for security. The actual values are correctly passed to your application as environment variables.

## Testing the Integration

1. Start ngrok, Django, and Vite as described above
2. In Vercel, navigate to your integration and click "Install"
3. Follow the installation flow
4. Click "Connect Account" to test SSO
5. You should be redirected to PostHog, authenticate, and return to Vercel

## Clean Up

When you're done testing:

```bash
# Stop ngrok
# Press Ctrl+C in the ngrok terminal

# Stop Django and Vite servers
# Press Ctrl+C in each terminal

# (Optional) Unset environment variables
direnv deny
```

## References

- [PostHog SSL Setup Documentation](../contents/handbook/engineering/setup-ssl-locally.md)
- [Vercel Marketplace API Docs](https://vercel.com/docs/integrations/create-integration/marketplace-api)
- [ngrok Documentation](https://ngrok.com/docs)
