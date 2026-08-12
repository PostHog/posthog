import { mcpKeys } from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/**
 * Object URL for an MCP server's brand icon from the authenticated logo.dev
 * proxy endpoint, or null while loading / when the domain has no icon (the
 * proxy 404s and callers render their own fallback glyph). Results never go
 * stale while observed; after cache eviction a revisit re-fetches, served by
 * the browser HTTP cache for hits, so transient proxy failures (e.g. an
 * exhausted logo.dev budget) heal instead of latching for the session.
 */
export function useServerIcon(
  domain: string | null,
  theme: "light" | "dark",
): string | null {
  const { data } = useAuthenticatedQuery(
    mcpKeys.icon(domain ?? "", theme),
    async (client) =>
      domain ? await client.getMcpServerIconUrl(domain, theme) : null,
    {
      enabled: !!domain,
      staleTime: Number.POSITIVE_INFINITY,
      retry: false,
    },
  );
  return data ?? null;
}
