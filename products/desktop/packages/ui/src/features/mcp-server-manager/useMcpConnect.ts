import type { IOAuthCallback } from "@posthog/core/mcp-servers/installFlow";
import type { useHostTRPCClient } from "@posthog/host-router/react";

export const mcpKeys = {
  servers: ["mcp", "servers"] as const,
  installations: ["mcp", "installations"] as const,
  icon: (domain: string, theme: "light" | "dark") =>
    ["mcp", "icon", domain, theme] as const,
  tools: (installationId: string) =>
    ["mcp", "installations", installationId, "tools"] as const,
};

type HostTRPCClient = ReturnType<typeof useHostTRPCClient>;

/** Host OAuth callback over the desktop's `mcpCallback` tRPC (deep link / dev
 *  HTTP). The one seam the install flow needs from the host. */
export function createOAuthCallback(
  trpcClient: HostTRPCClient,
): IOAuthCallback {
  return {
    getCallbackUrl: () => trpcClient.mcpCallback.getCallbackUrl.query(),
    openAndWaitForCallback: (args) =>
      trpcClient.mcpCallback.openAndWaitForCallback.mutate(args),
  };
}
