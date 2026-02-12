# Domain Connect

Automates DNS configuration for PostHog features that require users to add DNS records
(email sending, managed reverse proxy). Instead of manually copy-pasting records at their
DNS provider, users click a button and get redirected to approve pre-filled records.

Uses the [Domain Connect](https://www.domainconnect.org/) synchronous flow with request signing.

## How it works

```txt
User clicks "Configure automatically"
        │
        ▼
Frontend calls POST /api/environments/:id/integrations/domain-connect/apply-url
        │
        ▼
Backend resolves context (email/proxy) → domain, template variables, service ID
        │
        ▼
Backend builds signed apply URL → returns to frontend
        │
        ▼
Frontend opens URL in new tab → DNS provider shows pre-filled records
        │
        ▼
User approves → provider redirects back to PostHog with ?domain_connect=<context>
        │
        ▼
Frontend detects redirect param, cleans URL, parent component re-verifies
```

Two paths for provider detection:

1. **Auto-detection**: DNS TXT lookup on `_domainconnect.{domain}` reveals the provider.
   The banner shows "Your DNS is managed by {provider}" with a single button.
2. **Manual selection**: Auto-detection fails, but we show "I use {provider}" buttons for
   each provider in our allowlist. The user picks theirs.

## Architecture

### Backend (`posthog/domain_connect.py`)

Single module with all Domain Connect logic:

- **Discovery**: `discover_domain_connect()` — DNS TXT lookup + provider settings fetch, cached 1 hour
- **URL building**: `build_sync_apply_url()` / `build_provider_apply_url()` — constructs the redirect URL
- **Signing**: `sign_query_string()` — RSA-SHA256 signs the query string (required by Cloudflare)
- **Domain parsing**: `extract_root_domain_and_host()` — splits FQDNs handling multi-part TLDs
- **Context resolvers**: `resolve_email_context()` / `resolve_proxy_context()` — extracts template variables from the relevant PostHog resource
- **Provider allowlist**: `DOMAIN_CONNECT_PROVIDERS` dict — empty until providers accept our templates

### API endpoints (`posthog/api/integration.py`)

Two endpoints on `IntegrationViewSet`:

- `GET domain-connect/check?domain=` — checks if a domain's DNS provider supports Domain Connect
- `POST domain-connect/apply-url` — generates a signed apply URL for a given context (`email` or `proxy`)

### Frontend (this directory)

- **`domainConnectLogic.ts`** — Kea logic keyed by instance. Handles discovery check, URL generation,
  and redirect detection. All API interaction lives here.
- **`DomainConnectBanner.tsx`** — Drop-in banner component. Renders one of three states: auto-detected
  provider, manual provider buttons, or nothing.
- **`assets/`** — Local provider logos (Cloudflare for now).
- **`templates/`** — Backup copies of the Domain Connect template JSON files (see below).

### Settings

Two env vars in `posthog/settings/web.py`:

- `DOMAIN_CONNECT_PRIVATE_KEY` — PEM-encoded RSA private key for signing apply URLs
- `DOMAIN_CONNECT_KEY_ID` — Key identifier published via DNS (default: `_dck1`)

## Usage

Drop `DomainConnectBanner` anywhere DNS records need to be configured:

```tsx
<DomainConnectBanner
    logicKey={`email-${integration.id}`}
    domain="example.com"
    context="email"
    integrationId={integration.id}
/>

<DomainConnectBanner
    logicKey={`proxy-${record.id}`}
    domain={record.domain}
    context="proxy"
    proxyRecordId={record.id}
/>
```

Each instance gets its own keyed logic — no state sharing between banners.

## Adding a new context

To use Domain Connect for a new feature:

1. Create a template JSON in `templates/` and submit it to [Domain-Connect/Templates](https://github.com/Domain-Connect/Templates).
2. Add a `resolve_<context>_context()` function in `posthog/domain_connect.py` returning `(domain, service_id, variables)`.
3. Add the context branch in the `domain_connect_apply_url` endpoint in `posthog/api/integration.py`.
4. Add the context value to the `context` prop type in `domainConnectLogic.ts`.
5. Mount `<DomainConnectBanner>` with the new context in your UI.

## Adding a new DNS provider

1. Submit our templates to [Domain-Connect/Templates](https://github.com/Domain-Connect/Templates).
2. Contact the provider to register the templates in their store.
3. Once confirmed, add their `_domainconnect` TXT endpoint to `DOMAIN_CONNECT_PROVIDERS` in `posthog/domain_connect.py`.
4. Add the provider name to `DomainConnectProviderName` in `frontend/src/queries/schema/schema-general.ts` and run `hogli build:schema`.
5. Add their logo SVG to `assets/` and register it in `PROVIDER_LOGOS` in `DomainConnectBanner.tsx`.

## Templates

The `templates/` directory contains backup copies of the JSON files submitted to
[Domain-Connect/Templates](https://github.com/Domain-Connect/Templates). DNS providers
pull from that external repo — they do not read these files. We keep them here so the
canonical definitions live alongside the code.

| File                                     | Purpose                |
| ---------------------------------------- | ---------------------- |
| `posthog.com.email-verification-us.json` | Email DNS records (US) |
| `posthog.com.email-verification-eu.json` | Email DNS records (EU) |
| `posthog.com.reverse-proxy-us.json`      | Proxy CNAME (US)       |
| `posthog.com.reverse-proxy-eu.json`      | Proxy CNAME (EU)       |

## Tests

Backend tests live at `posthog/test/test_domain_connect.py` (25 tests covering domain
parsing, region mapping, URL building, signing, discovery, and provider listing).
