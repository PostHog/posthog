import { GatewayAddServer } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayAddServer";
import { GatewayAgentDetail } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayAgentDetail";
import { GatewayAuditLog } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayAuditLog";
import { GatewayMemberDetail } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayMemberDetail";
import { GatewayRail } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayRail";
import { GatewayServerDetail } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayServerDetail";
import { GatewayServersHome } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayServersHome";
import { GatewayTeamSettings } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayTeamSettings";
import { GatewayTeamView } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayTeamView";
import {
  type GatewayRoute,
  isRouteAllowed,
} from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import { useGatewayConfig } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayConfig";
import { useGatewayServers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayServers";
import { DotPatternBackground } from "@posthog/ui/primitives/DotPatternBackground";
import { Box, Flex, ScrollArea } from "@radix-ui/themes";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

/**
 * Team MCP gateway: one control plane for the servers a team runs, who can
 * reach them (members and agent service accounts), per-tool policies per
 * scope, and the audit log. Renders behind the `mcp-gateway` flag in place of
 * the per-user marketplace.
 */
export function McpGatewayView() {
  const queryClient = useQueryClient();
  const [requestedRoute, setRoute] = useState<GatewayRoute>({
    view: "servers",
  });

  const { isAdmin, allowCustomServers, canManageAgentAccess, configLoading } =
    useGatewayConfig();
  const canAddServers = isAdmin || allowCustomServers;
  const gateway = useGatewayServers();

  // Refresh gateway state when the window regains focus — connections and
  // policies can change from the web app or another teammate meanwhile.
  useEffect(() => {
    const refresh = () => {
      queryClient.invalidateQueries({ queryKey: ["mcp"] });
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [queryClient]);

  // Role guard, applied at render: if the config resolves to a narrower role
  // than the stored route needs, show the servers home instead.
  const route: GatewayRoute =
    configLoading || isRouteAllowed(requestedRoute, { isAdmin, canAddServers })
      ? requestedRoute
      : { view: "servers" };

  const mainContent = (() => {
    switch (route.view) {
      case "add":
        return (
          <GatewayAddServer
            isAdmin={isAdmin}
            canManageAgentAccess={canManageAgentAccess}
            onNavigate={setRoute}
          />
        );
      case "server":
        return (
          <GatewayServerDetail
            key={route.serverId}
            serverId={route.serverId}
            initialScope={route.scope}
            isAdmin={isAdmin}
            canManageAgentAccess={canManageAgentAccess}
            onNavigate={setRoute}
          />
        );
      case "team":
        return <GatewayTeamView onNavigate={setRoute} />;
      case "agent":
        return (
          <GatewayAgentDetail
            key={route.accountId}
            accountId={route.accountId}
            onNavigate={setRoute}
          />
        );
      case "member":
        return (
          <GatewayMemberDetail
            key={route.userId}
            userId={route.userId}
            onNavigate={setRoute}
          />
        );
      case "settings":
        return <GatewayTeamSettings onNavigate={setRoute} />;
      case "audit":
        return <GatewayAuditLog />;
      default:
        return (
          <GatewayServersHome
            isAdmin={isAdmin}
            canAddServers={canAddServers}
            onNavigate={setRoute}
          />
        );
    }
  })();

  return (
    <Flex height="100%" className="min-h-0 overflow-hidden">
      <GatewayRail
        servers={gateway.servers}
        templatesById={gateway.templatesById}
        isAdmin={isAdmin}
        canAddServers={canAddServers}
        route={route}
        onNavigate={setRoute}
      />
      <Box className="relative min-h-0 min-w-0 flex-1">
        <DotPatternBackground />
        <ScrollArea className="h-full w-full">
          <Box p="6" mx="auto" className="relative z-[1] max-w-[960px]">
            {mainContent}
          </Box>
        </ScrollArea>
      </Box>
    </Flex>
  );
}
