import type { CloudRegion } from "@posthog/shared";

/**
 * Resolve the agent-ingress base URL for live (streaming) calls, derived per
 * region the same way the PostHog API base is (`getCloudUrlFromRegion`).
 *
 * In `dev` the backend hands out a trycloudflare quick-tunnel URL in
 * `ingress_base_url`, and those tunnels BUFFER SSE — so `/listen` never streams
 * incrementally through them. The local agent-ingress (localhost:3030) streams
 * fine, so for `dev` we keep the record's `/agents/<slug>` path but point the
 * origin at the local ingress. us/eu ingress URLs stream natively, so their
 * (region-correct) `ingress_base_url` is used as-is.
 */
const LOCAL_INGRESS_ORIGIN = "http://localhost:3030";

export function resolveIngressBaseUrl(
  ingressBaseUrl: string | null | undefined,
  region: CloudRegion | null,
): string | null {
  if (!ingressBaseUrl) return null;
  if (region === "dev") {
    return ingressBaseUrl.replace(/^https?:\/\/[^/]+/, LOCAL_INGRESS_ORIGIN);
  }
  return ingressBaseUrl;
}

/**
 * Construct an agent's ingress base URL from `(slug, region)` alone, without
 * loading its API record. The ingress is slug-routed and team-agnostic (the
 * slug is a single global namespace), so this resolves an agent from any
 * project — including one the agent isn't hosted in. Mirrors the deployed
 * routing config (charts `AGENT_INGRESS_*`): us/eu address agents in domain mode
 * (`<slug>.agents.<region>.posthog.com`); local dev uses the path-mode local
 * ingress, which streams SSE (the dev quick-tunnel buffers it).
 *
 * Use this for first-party agents reachable cross-project (the agent builder).
 * Per-agent console views stay on {@link resolveIngressBaseUrl} + the record,
 * which carries other fields and is correctly project-scoped.
 */
export function agentIngressBaseUrl(
  slug: string,
  region: CloudRegion | null,
): string | null {
  if (!slug || !region) return null;
  switch (region) {
    case "us":
      return `https://${slug}.agents.us.posthog.com`;
    case "eu":
      return `https://${slug}.agents.eu.posthog.com`;
    case "dev":
      return `${LOCAL_INGRESS_ORIGIN}/agents/${slug}`;
  }
}
