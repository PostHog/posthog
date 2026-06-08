# Public subdomain routing for the agent platform

**Status:** infra scaffolded, application ordering documented. Apply in the
sequence below — the steps are decoupled but each later step relies on the
earlier one being live.

## Endpoints we're publishing

- `agents.<env>.posthog.<tld>` — agent-ingress root. Covered by the
  existing `*.<env>.posthog.<tld>` wildcard cert.
- `<slug>.agents.<env>.posthog.<tld>` — agent-ingress, live revision.
  **Needs a new wildcard cert** for `*.agents.<env>.posthog.<tld>`.
- `<slug>-<rev>.agents.<env>...` — agent-ingress, specific revision.
  Same cert as the live form.
- `agent-console.<env>.posthog.<tld>` — agent-console. Covered by the
  existing `*.<env>.posthog.<tld>` wildcard cert.

The `<rev>.<slug>.agents...` form (revision as a separate subdomain label)
would require a wildcard cert two levels deep, which TLS doesn't allow with
a single cert. The resolver supports both shapes
([`services/agent-ingress/src/routing/resolver.ts`](../../../services/agent-ingress/src/routing/resolver.ts):`extractSlugFromHost`),
so we use the `<slug>-<rev>` form (one wildcard, no per-agent cert).

## Per-env apply sequence

### dev (`*.agents.dev.posthog.dev`)

1. **Apply the cert + DNS** in cloud-infra. The terraform is already in
   the tree at
   [`terraform/environments/aws-accnt-dev/us-east-1/route53/route53-agent-platform.tf`](https://github.com/PostHog/posthog-cloud-infra/blob/agents-prod-readiness/terraform/environments/aws-accnt-dev/us-east-1/route53/route53-agent-platform.tf).

   ```bash
   cd posthog-cloud-infra/terraform/environments/aws-accnt-dev/us-east-1/route53
   terragrunt apply
   ```

   Capture the `agents_wildcard_certificate_arn` output.

2. **Wire the cert into the dev ALB.** In `posthog/charts`:

   ```yaml
   # argocd/ingress/values/values.dev.yaml
   annotations:
     alb.ingress.kubernetes.io/certificate-arn: <existing>,<new-cert-arn-from-step-1>
   ```

   Push; ArgoCD picks up the change and the listener gets a third cert.

3. **Confirm DNS + cert.** Should be live within a couple minutes:

   ```bash
   dig +short '*.agents.dev.posthog.dev'          # → dev ALB
   curl -fsS https://agents.dev.posthog.dev/livez # → 200 from agent-ingress
   ```

   Per-agent host:

   ```bash
   curl -fsS https://my-agent.agents.dev.posthog.dev/livez
   ```

4. **Register OAuth callback.** In the dev PostHog OAuth admin, add
   `https://agent-console.dev.posthog.dev/api/auth/callback` as a redirect
   URI on the agent-console OAuth app. The chart already sets the
   `CONSOLE_BASE_URL` env to the new host.

### prod-us (`*.agents.us.posthog.com`)

1. **Provision the wildcard ACM cert** in account `854902948032`
   (`us-east-1`). The dev terraform is the canonical pattern; replicate
   into the prod-us tree (no public route53 module here — `posthog.com` is
   on Cloudflare, not Route53).

2. **Add the Cloudflare CNAME** for `*.agents.us.posthog.com` pointing at
   the prod-us cluster ALB:

   ```text
   *.agents.us.posthog.com  CNAME  <posthog-ingress-prod-us ALB DNS>  proxied=false
   ```

   Look up the ALB DNS in the AWS console (LB name
   `posthog-ingress-prod-us`).

3. **Wire the cert into the prod-us ALB**:

   ```yaml
   # argocd/ingress/values/values.prod-us.yaml
   alb.ingress.kubernetes.io/certificate-arn: <existing>,<new-cert-arn>
   ```

4. **Smoke test** as in dev. `curl https://agents.us.posthog.com/livez`.

5. **Register prod-us OAuth callback**:
   `https://agent-console.us.posthog.com/api/auth/callback`.

### prod-eu (`*.agents.eu.posthog.com`)

Same as prod-us, in account `730758685644` (`eu-central-1`). New ACM cert,
new Cloudflare CNAME `*.agents.eu.posthog.com` → prod-eu ALB DNS, append
cert ARN to `argocd/ingress/values/values.prod-eu.yaml`, register OAuth
callback for `agent-console.eu.posthog.com`.

## What's already wired in the charts PR

- Public `ingress:` block on
  [`apps/agent-ingress/values.{dev,prod-us,prod-eu}.yaml`](https://github.com/PostHog/charts/tree/agents-prod-readiness/apps/agent-ingress)
  with `host`, `defaultRoute`, and `env.ROUTING_MODE=domain` +
  `env.DOMAIN_SUFFIX`.
- Public `ingress:` block on
  [`apps/agent-console/values.{dev,prod-us,prod-eu}.yaml`](https://github.com/PostHog/charts/tree/agents-prod-readiness/apps/agent-console)
  with the new public host (Tailscale ingress dropped in dev).
- `EXTRA_CSRF_TRUSTED_ORIGINS` added to
  [`shared/posthog-django/common.{env}.yaml`](https://github.com/PostHog/charts/tree/agents-prod-readiness/shared/posthog-django)
  so OAuth POSTs from the new subdomains pass CSRF.
- `TODO(agent-platform)` markers on the three
  `argocd/ingress/values/values.{env}.yaml` files where Ben pastes the new
  cert ARN once the cert exists.

## Failure modes to expect on rollout

- **Stale `ROUTING_MODE=path` resolver bug:** the agent-ingress was
  running in `path` mode before this change. After flipping to `domain`,
  requests under `/agents/<slug>/...` 404 because the path prefix
  matcher is no longer wired. Migrate any consumers (Django proxies,
  custom integrations) to send Host-routed requests, or run in `path`
  mode in parallel until they catch up.

- **Cookie scoping:** PostHog session cookies on `app.<env>.posthog.<tld>`
  don't reach the agent subdomain. agent-console runs its own OAuth +
  sealed-cookie session — it doesn't try to share the main app's
  session. Same-tab navigation between `app.*` and `agent-console.*`
  will trigger a fresh OAuth dance the first time.

- **Tailscale dev fallback gone:** dropping `tailscaleIngress` on
  `agent-console` removes the `agent-console-dev.hedgehog-kitefin.ts.net`
  URL. If anyone was relying on it, point them at
  `agent-console.dev.posthog.dev` instead.
