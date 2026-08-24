import type { GatewayPolicyScope } from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";

/** In-page navigation state for the gateway scene (single flat route). */
export type GatewayRoute =
  | { view: "servers" }
  | { view: "server"; serverId: string; scope?: GatewayPolicyScope }
  | { view: "add" }
  | { view: "team" }
  | { view: "agent"; accountId: string }
  | { view: "member"; userId: number }
  | { view: "settings" }
  | { view: "audit" };

// The audit log is open to every member: the backend scopes it to calls made
// through the caller's own connections unless they administer the gateway.
const ADMIN_ONLY_VIEWS: GatewayRoute["view"][] = [
  "team",
  "agent",
  "member",
  "settings",
];

/** Keep the route inside what the caller's role may see. */
export function isRouteAllowed(
  route: GatewayRoute,
  options: { isAdmin: boolean; canAddServers: boolean },
): boolean {
  if (ADMIN_ONLY_VIEWS.includes(route.view)) return options.isAdmin;
  if (route.view === "add") return options.canAddServers;
  return true;
}
