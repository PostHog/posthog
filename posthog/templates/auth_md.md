{% autoescape off %}# PostHog

PostHog is an open-source platform for product analytics, session replay, feature flags, experiments, surveys, and data warehousing.

## Creating an account

- AI wizard: `npx @posthog/wizard@latest --signup` creates a new account and project from the command line, with no signup form. This is the most direct path for a new user. See https://posthog.com/docs/ai-engineering/ai-wizard
- Provisioning API: partners and platforms can create accounts for their users and deep-link them in. See https://posthog.com/docs/integrate/provisioning

## Authenticating an existing user

- OAuth 2.0: standard authorization-code flow for an app acting on behalf of a user. See https://posthog.com/docs/api/oauth
- Personal API keys: long-lived keys for scripts and server-to-server use. See https://posthog.com/docs/api#authentication

## Agent registration via ID-JAG (Enterprise, beta)

Available on the Enterprise plan with XAA enabled, and currently in beta, so most clients should use one of the options above. With it configured, an agent presents an [ID-JAG](https://xaa.dev) identity assertion (`identity_assertion`) to the token endpoint using the JWT-bearer grant (`urn:ietf:params:oauth:grant-type:jwt-bearer`) and receives a scoped, short-lived OAuth access token bound to the user. See https://posthog.com/docs/settings/id-jag

- Identity endpoint: `{{ base_url }}/oauth/token/`
- Assertion type: `urn:ietf:params:oauth:token-type:id-jag`
- Protected resource metadata: `{{ base_url }}/.well-known/oauth-protected-resource`
- Authorization server metadata: `{{ base_url }}/.well-known/oauth-authorization-server`

The user-claimed device flow (`service_auth`, `anonymous`) is not supported yet.

## Scopes

{% for scope, description in scopes %}- `{{ scope }}`: {{ description }}
{% endfor %}

## Changing scopes

Access tokens carry the scope set granted when they were issued.
Scopes do not change on refresh. Refreshing a token returns the same or narrower scopes, never more.

If your app needs additional scopes, for example a newly required scope, or a request that returns `403` because the token is missing a required scope, start a new authorization at `{{ base_url }}/oauth/authorize/`.
The user re-consents and the new token carries the updated scopes.
PostHog does not push new scopes to existing tokens; the client must re-authorize.

## Links

- Pricing: https://posthog.com/pricing
- Terms: https://posthog.com/terms
- Privacy: https://posthog.com/privacy
- API docs: https://posthog.com/docs/api
- Contact: hey@posthog.com
{% endautoescape %}
