import { useServiceOptional } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { McpToolView } from "@posthog/ui/features/mcp-apps/components/McpToolView";
import {
  resolveMcpToolPair,
  selectMcpAppResource,
} from "@posthog/ui/features/mcp-apps/utils/mcp-app-host-utils";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import {
  MCP_APP_HOST_COMPONENT,
  type McpAppHostComponent,
} from "../identifiers";

interface McpToolBlockProps extends ToolViewProps {
  mcpToolName: string;
}

export function McpToolBlock(props: McpToolBlockProps) {
  const { mcpToolName, toolCall } = props;
  const { serverName, toolName } = resolveMcpToolPair(
    toolCall._meta,
    mcpToolName,
  );

  const mcpAppsDisabled = useSettingsStore((s) => s.mcpAppsDisabledServers);
  const isDisabledForServer = mcpAppsDisabled.includes(serverName);

  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const McpAppHost = useServiceOptional<McpAppHostComponent>(
    MCP_APP_HOST_COMPONENT,
  );

  const { data: hasUiByTool } = useQuery(
    trpc.mcpApps.hasUiForTool.queryOptions(
      { toolKey: mcpToolName },
      {
        staleTime: Infinity,
        enabled:
          !isDisabledForServer &&
          selectMcpAppResource(toolCall.rawOutput, false) === null,
      },
    ),
  );

  const resourceSelection = selectMcpAppResource(
    toolCall.rawOutput,
    hasUiByTool,
  );

  useSubscription(
    trpc.mcpApps.onDiscoveryComplete.subscriptionOptions(undefined, {
      enabled: !isDisabledForServer,
      onData: (_event) => {
        void queryClient.invalidateQueries(
          trpc.mcpApps.getToolDefinition.pathFilter(),
        );
        if (resourceSelection?.source === "result") {
          void queryClient.invalidateQueries(
            trpc.mcpApps.getUiResourceByUri.pathFilter(),
          );
        } else {
          void queryClient.invalidateQueries(
            trpc.mcpApps.hasUiForTool.pathFilter(),
          );
          void queryClient.invalidateQueries(
            trpc.mcpApps.getUiResource.pathFilter(),
          );
        }
      },
    }),
  );

  return (
    <>
      <McpToolView {...props} />
      {resourceSelection && !isDisabledForServer && McpAppHost && (
        <McpAppHost
          {...props}
          serverName={serverName}
          toolName={toolName}
          resourceUri={
            resourceSelection.source === "result"
              ? resourceSelection.resourceUri
              : undefined
          }
        />
      )}
    </>
  );
}
