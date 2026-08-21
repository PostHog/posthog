import {
  POSTHOG_EXEC_TOOL_KEY,
  resolveResultResourceUri,
} from "@posthog/core/mcp-apps/schemas";
import { useServiceOptional } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { McpToolView } from "@posthog/ui/features/mcp-apps/components/McpToolView";
import { parseMcpToolKey } from "@posthog/ui/features/mcp-apps/utils/mcp-app-host-utils";
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
  const { serverName, toolName } = parseMcpToolKey(mcpToolName);

  const isExec = mcpToolName === POSTHOG_EXEC_TOOL_KEY;
  const execResourceUri = isExec
    ? resolveResultResourceUri(toolCall.rawOutput)
    : undefined;

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
        enabled: !isDisabledForServer && !isExec,
      },
    ),
  );

  const hasUi = isExec ? !!execResourceUri : hasUiByTool;

  useSubscription(
    trpc.mcpApps.onDiscoveryComplete.subscriptionOptions(undefined, {
      enabled: !isDisabledForServer,
      onData: (_event) => {
        if (isExec) {
          void queryClient.invalidateQueries(
            trpc.mcpApps.getUiResourceByUri.pathFilter(),
          );
          return;
        }
        void queryClient.invalidateQueries(
          trpc.mcpApps.hasUiForTool.pathFilter(),
        );
        void queryClient.invalidateQueries(
          trpc.mcpApps.getUiResource.pathFilter(),
        );
      },
    }),
  );

  return (
    <>
      <McpToolView {...props} />
      {hasUi && !isDisabledForServer && McpAppHost && (
        <McpAppHost {...props} serverName={serverName} toolName={toolName} />
      )}
    </>
  );
}
