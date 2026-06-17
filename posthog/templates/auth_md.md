{% autoescape off %}# PostHog

PostHog is an open-source platform for product analytics, session replay, feature flags, experiments, surveys, and data warehousing.

## Registration

PostHog supports agent registration via identity assertion (`identity_assertion`). An agent presents an [ID-JAG](https://xaa.dev) identity assertion at the identity endpoint and receives a scoped, short-lived OAuth access token bound to the user.

- Identity endpoint: `{{ base_url }}/id-jag/token`
- Assertion type: `urn:ietf:params:oauth:token-type:id-jag`
- Protected resource metadata: `{{ base_url }}/.well-known/oauth-protected-resource`
- Authorization server metadata: `{{ base_url }}/.well-known/oauth-authorization-server`

The user-claimed device flow (`service_auth`, `anonymous`) is not supported yet.

## Scopes

{% for scope, description in scopes %}- `{{ scope }}` — {{ description }}
{% endfor %}

## Links

- Pricing: https://posthog.com/pricing
- Terms: https://posthog.com/terms
- Privacy: https://posthog.com/privacy
- API docs: https://posthog.com/docs/api
- Contact: hey@posthog.com
{% endautoescape %}
