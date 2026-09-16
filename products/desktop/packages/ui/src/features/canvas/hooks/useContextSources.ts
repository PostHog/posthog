import {
  type ResolvedContextSource,
  resolveContextSources,
} from "@posthog/core/canvas/contextSources";
import { useMcpServers } from "@posthog/ui/features/mcp-servers/hooks/useMcpServers";
import { useMemo } from "react";

export interface ContextSourceState extends ResolvedContextSource {
  /** True while the browser authorization for this source is open. */
  connecting: boolean;
}

export interface ContextSources {
  sources: ContextSourceState[];
  isLoading: boolean;
  connect: (state: ContextSourceState) => void;
  byId: (id: string) => ContextSourceState | undefined;
}

/** The external sources this space can link, with whether each one's MCP server is connected. */
export function useContextSources(): ContextSources {
  const {
    servers,
    serversLoading,
    installations,
    installationsLoading,
    installingId,
    installTemplate,
    reauthorize,
    reauthorizePending,
  } = useMcpServers();

  const sources = useMemo<ContextSourceState[]>(
    () =>
      resolveContextSources(servers ?? [], installations ?? []).map(
        (resolved) => ({
          ...resolved,
          connecting:
            installingId === resolved.template.id ||
            (reauthorizePending && resolved.status === "needs_reauth"),
        }),
      ),
    [servers, installations, installingId, reauthorizePending],
  );

  return {
    sources,
    isLoading: serversLoading || installationsLoading,
    connect: (state) => {
      if (state.installation && state.status !== "connected") {
        reauthorize(state.installation.id);
      } else {
        installTemplate(state.template);
      }
    },
    byId: (id) => sources.find((state) => state.source.id === id),
  };
}
