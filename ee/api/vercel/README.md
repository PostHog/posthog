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

2. **Redirect URL**: Set to `{your_ngrok_url}/connect/vercel/callback`
   - This enables the "Link Existing Account" connectable account flow
   - Example: `https://abc123.ngrok-free.dev/connect/vercel/callback`

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

### Connectable Account Flow (Link Existing Account)

When a user clicks "Link Existing Account" in the Vercel Marketplace:

1. Vercel opens a popup to our **Redirect URL** (`/connect/vercel/callback`) with an OAuth code
2. PostHog exchanges the code for an access token via `POST /v2/oauth/access_token`
3. If the user isn't logged in, they're redirected to `/login` first
4. The user selects which PostHog organization to link
5. An `OrganizationIntegration` record is created with `type=connectable`
6. The popup closes and returns the user to Vercel

Billing stays with PostHog for connected accounts - no billing provider migration is needed.

## Troubleshooting

### "This host is not allowed" from Vite

**Solution**: Add ngrok domains to `allowedHosts` in vite.config.ts (see Step 3)

### CORS errors when loading JavaScript assets

**Solution**: Add your ngrok domain to the `cors.origin` array in vite.config.ts (see Step 3)

### JWT validation failing with "Audience doesn't match"

**Solution**: Verify `VERCEL_CLIENT_INTEGRATION_ID` matches your Vercel integration's Client ID exactly

### Getting 400/404 errors during installation

**Solution**:

1. Verify Configuration URL points to your Django ngrok tunnel (port 8000)
2. Verify Redirect URL is set to `{ngrok_url}/connect/vercel/callback`
3. Check Django logs for detailed error messages

### Blank page (React not mounting) after switching branches

Vite caches resolved module paths in `node_modules/.pnpm`.
When you switch branches, pnpm store hashes can change, leaving Vite with stale references (typically `@react-refresh` returns 500).

**Solution**: Restart the Vite dev server.
You can verify by checking `curl -s -o /dev/null -w "%{http_code}" http://localhost:8234/@react-refresh` — it should return 200.

### Environment variables not loaded

**Solution**:

1. Verify you're authenticated with 1Password CLI: `op whoami`
2. Test credential loading: `op run --env-file=.env.vercel -- printenv | grep VERCEL`
3. Restart your Django server
4. Verify ngrok URL is set: Check that `JS_URL` and `NGROK_ORIGIN` in your `.env.vercel` match your ngrok tunnel URL

### `JS_URL` doesn't affect Vite dev scripts

In development, the Vite dev server script tags (`@vite/client`, `@react-refresh`, `src/index.tsx`) are hardcoded to `http://localhost:8234` in `posthog/utils.py`.
`JS_URL` only sets `window.JS_URL` for the production bundle loader.
Browsers exempt `localhost` from mixed content blocking, so this works even when the page is served over HTTPS via ngrok.

### 1Password shows "<concealed by 1Password>" in logs

This is normal! 1Password CLI conceals sensitive values in stdout for security. The actual values are correctly passed to your application as environment variables.

## Testing the Integration

### Automated Tests

Run the Vercel integration test suite:

```bash
pytest ee/vercel/test/test_integration.py -v
```

The test suite includes:

- **Unit tests**: Individual function testing
- **Regression tests**: Tests for specific bugs that were fixed (see `TestVercelInstallationRegressions`)
- **E2E tests**: Complete installation flow simulations (see `TestVercelInstallationE2E`)

### Manual Testing Checklist

Before releasing changes to the Vercel integration, manually verify the following scenarios:

#### Scenario 1: Brand New User Installation

**Setup**: Use an email that doesn't exist in PostHog

1. Start ngrok, Django, and Vite as described above
2. In Vercel, navigate to your integration and click "Install"
3. Complete the installation flow

**Expected**:

- [ ] Installation completes without errors
- [ ] New organization is created in PostHog
- [ ] New user is created with the email from Vercel
- [ ] User is added as Owner of the organization
- [ ] Click "Connect Account" → SSO works immediately (no login required)

#### Scenario 2: Existing PostHog User (No Prior Vercel)

**Setup**: Create a PostHog account manually with an email, then use that email in Vercel

1. Create a user in PostHog: `User.objects.create_user(email="test@example.com", password="test")`
2. In Vercel, install with the same email

**Expected**:

- [ ] Installation completes without errors
- [ ] New organization is created
- [ ] Existing user is added as Owner of the new organization
- [ ] Click "Connect Account" → User is prompted to login (security: must prove ownership)
- [ ] After login, SSO works

#### Scenario 3: Trusted Vercel User (Second Installation)

**Setup**: User who already has one Vercel installation

1. Complete Scenario 1 first
2. Install a second Vercel integration with the same email

**Expected**:

- [ ] Installation completes without errors
- [ ] Second organization is created
- [ ] Same user is added as Owner of the second organization
- [ ] Click "Connect Account" → SSO works immediately (user is trusted)

#### Scenario 4: Inactive User Reactivation

**Setup**: Create an inactive user, then install with that email

1. Create inactive user: `User.objects.create_user(email="inactive@example.com", password="test", is_active=False)`
2. Install Vercel integration with that email

**Expected**:

- [ ] Installation completes without errors
- [ ] User is reactivated (is_active=True)
- [ ] User is added to the new organization

#### Scenario 5: Link Existing Account (Connectable Account)

**Setup**: Have an existing PostHog account with admin access to an organization

1. In the Vercel Marketplace, click "Add" on the PostHog integration
2. Choose "Link Existing Account"
3. A popup opens — log in with your PostHog credentials
4. Select an organization from the dropdown
5. Click "Connect organization"

**Expected**:

- [ ] Popup opens to PostHog login page (if not already logged in)
- [ ] After login, org selector is shown with orgs where user is admin/owner
- [ ] Already-linked orgs are not available for selection
- [ ] Clicking "Connect organization" shows success message
- [ ] "Return to Vercel" button redirects back to Vercel
- [ ] `OrganizationIntegration` record created with `config.type = "connectable"`

#### Quick Local Verification

To quickly verify the fix for existing users without Vercel mappings:

```python
# In Django shell: python manage.py shell
from posthog.models.user import User
from posthog.models.organization_integration import OrganizationIntegration

# Create test user without any Vercel mappings
User.objects.create_user(email="test-vercel@example.com", password="test", first_name="Test")

# Verify no Vercel mappings exist
for oi in OrganizationIntegration.objects.filter(kind="vercel"):
    mappings = oi.config.get("user_mappings", {})
    user_ids = list(mappings.values())
    user = User.objects.filter(email="test-vercel@example.com").first()
    assert user.pk not in user_ids, "User should have no mappings"

# Now install via Vercel with test-vercel@example.com
# User should be added to org without errors
```

### Basic Manual Testing

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
