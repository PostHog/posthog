import {
  ArrowClockwise,
  ArrowLeft,
  ArrowUpRight,
  Check,
  Key,
  MagnifyingGlass,
  Plus,
  Prohibit,
  Robot,
  Shield,
  Trash,
  User,
  Users,
  X,
} from "@phosphor-icons/react";
import type {
  McpAgentGrantScope,
  McpApprovalState,
  McpGatewayServer,
} from "@posthog/api-client/posthog-client";
import {
  type GatewayConnectCredentials,
  gatewayConnectAuthType,
  gatewayConnectNeedsCredentials,
} from "@posthog/core/mcp-gateway/gatewayConnect";
import {
  agentShareMessage,
  countPoliciesByState,
  formatAgo,
  getGatewayServerRemovalAction,
} from "@posthog/core/mcp-gateway/gatewayServers";
import { usableInstallationId } from "@posthog/core/mcp-gateway/gatewayToolDiscovery";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { AgentScopeToggle } from "@posthog/ui/features/mcp-gateway/components/parts/AgentScopeToggle";
import {
  gatewayUserName,
  RobotAvatar,
} from "@posthog/ui/features/mcp-gateway/components/parts/avatars";
import { GatewayConnectDialog } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayConnectDialog";
import { GatewayDeleteServerDialog } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayDeleteServerDialog";
import { GatewayToolRow } from "@posthog/ui/features/mcp-gateway/components/parts/GatewayToolRow";
import { GiveAccessDialog } from "@posthog/ui/features/mcp-gateway/components/parts/GiveAccessDialog";
import type { GatewayRoute } from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import {
  type GatewayPolicyScope,
  TEAM_SCOPE,
  YOU_SCOPE,
} from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import { useGatewayMembers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayMembers";
import { useGatewayServers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayServers";
import { useGatewayToolPolicies } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayToolPolicies";
import { useServiceAccounts } from "@posthog/ui/features/mcp-gateway/hooks/useServiceAccounts";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { toast } from "@posthog/ui/primitives/toast";
import {
  Badge,
  Button,
  Flex,
  IconButton,
  Separator,
  Spinner,
  Switch,
  Text,
  TextField,
  Tooltip,
} from "@radix-ui/themes";
import { useMemo, useState } from "react";

const TOOL_PREVIEW_LIMIT = 10;

interface GatewayServerDetailProps {
  serverId: string;
  initialScope?: GatewayPolicyScope;
  isAdmin: boolean;
  canManageAgentAccess: boolean;
  onNavigate: (route: GatewayRoute) => void;
}

function sameScope(a: GatewayPolicyScope, b: GatewayPolicyScope): boolean {
  return (
    a.scopeType === b.scopeType &&
    a.scopeUserId === b.scopeUserId &&
    a.scopeServiceAccountId === b.scopeServiceAccountId
  );
}

export function GatewayServerDetail({
  serverId,
  initialScope,
  isAdmin,
  canManageAgentAccess,
  onNavigate,
}: GatewayServerDetailProps) {
  const gateway = useGatewayServers();
  const server = gateway.servers.find((entry) => entry.id === serverId);
  const [scope, setScope] = useState<GatewayPolicyScope>(
    initialScope ?? YOU_SCOPE,
  );
  const [giveAccessOpen, setGiveAccessOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [deleteServerOpen, setDeleteServerOpen] = useState(false);
  const [toolSearch, setToolSearch] = useState("");
  const [toolsExpanded, setToolsExpanded] = useState(false);

  // Listing tools from the upstream server needs a live credential of the
  // caller's own — it is what the gateway authenticates the list call with.
  const liveInstallationId = usableInstallationId(server ?? null);

  const tools = useGatewayToolPolicies(serverId, scope, {
    enabled: !!server,
    autoDiscoverWith: liveInstallationId,
  });
  const filteredPolicies = useMemo(() => {
    const search = toolSearch.trim().toLowerCase();
    if (!search) return tools.policies;
    return tools.policies.filter((policy) =>
      policy.tool_name.toLowerCase().includes(search),
    );
  }, [toolSearch, tools.policies]);
  const displayedPolicies = toolsExpanded
    ? filteredPolicies
    : filteredPolicies.slice(0, TOOL_PREVIEW_LIMIT);
  // Team-scope rows seed the give-access dialog's per-tool defaults.
  const teamTools = useGatewayToolPolicies(serverId, TEAM_SCOPE, {
    enabled: !!server && canManageAgentAccess,
  });
  const members = useGatewayMembers({ enabled: isAdmin });
  const serviceAccounts = useServiceAccounts();
  // `server.connections` is admin-only (empty for members), so identifying
  // the caller as a custom server's creator needs the session user instead.
  const apiClient = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client: apiClient });

  const scopes = useMemo<GatewayPolicyScope[]>(() => {
    if (!server) return [];
    const list: GatewayPolicyScope[] = isAdmin
      ? [TEAM_SCOPE, YOU_SCOPE]
      : [YOU_SCOPE];
    if (
      initialScope?.scopeType === "member" &&
      initialScope.scopeUserId !== undefined
    ) {
      list.push(initialScope);
    }
    if (canManageAgentAccess) {
      // One chip per agent: an agent shared by several members carries one
      // access row per sharer, but its tool policy is a single agent scope.
      const seenAgentIds = new Set<string>();
      for (const agent of server.agents) {
        if (seenAgentIds.has(agent.service_account_id)) continue;
        seenAgentIds.add(agent.service_account_id);
        list.push({
          scopeType: "agent",
          scopeServiceAccountId: agent.service_account_id,
          label: agent.name,
        });
      }
    }
    return list;
  }, [server, isAdmin, canManageAgentAccess, initialScope]);

  if (!server) {
    return (
      <Flex direction="column" gap="4">
        <BackButton onNavigate={onNavigate} />
        <Flex align="center" justify="center" py="6">
          {gateway.serversLoading ? (
            <Spinner size="2" />
          ) : (
            <Text color="gray" className="text-sm">
              Server not found.
            </Text>
          )}
        </Flex>
      </Flex>
    );
  }

  const yourConnection = server.your_connection;
  const selfEnabled = yourConnection ? yourConnection.is_enabled : true;
  const needsReconnect =
    !!yourConnection &&
    (yourConnection.needs_reauth || yourConnection.pending_oauth);
  const connecting = gateway.connectingServerId === server.id;
  const template = server.template_id
    ? gateway.templatesById.get(server.template_id)
    : undefined;
  const serverRemovalAction = getGatewayServerRemovalAction(
    server,
    isAdmin,
    currentUser?.id ?? null,
  );
  const deletesForEveryone = serverRemovalAction === "delete_for_everyone";
  const deleteInstallationId =
    serverRemovalAction === "delete_for_you"
      ? (yourConnection?.installation_id ?? null)
      : null;

  const agentScope = scope.scopeType === "agent";
  const counts = countPoliciesByState(tools.policies, scope.scopeType);
  const editableCount = tools.policies.filter(
    (policy) => !policy.locked,
  ).length;
  const filteredEditablePolicies = filteredPolicies.filter(
    (policy) => !policy.locked,
  );
  const hasToolSearch = toolSearch.trim().length > 0;
  const bulkEditableCount = hasToolSearch
    ? filteredEditablePolicies.length
    : editableCount;
  const scopeEditable =
    isAdmin ||
    scope.scopeType === "member" ||
    (scope.scopeType === "agent" && canManageAgentAccess);
  // Any connected member can re-list — it runs against their own credential,
  // and it is the manual retry when auto-discovery failed.
  const refreshInstallationId = liveInstallationId;
  const showScopeBar = (isAdmin || canManageAgentAccess) && scopes.length > 1;

  const setBulkPolicy = (state: McpApprovalState) => {
    tools.setAll(
      state,
      hasToolSearch
        ? filteredEditablePolicies.map((policy) => policy.tool_name)
        : undefined,
    );
  };

  const connectButton = connecting ? (
    <Button variant="solid" size="2" disabled>
      <Spinner size="1" /> Authorizing…
    </Button>
  ) : needsReconnect ? (
    <Button
      variant="solid"
      size="2"
      onClick={() =>
        gateway.reconnect({
          installationId: yourConnection.installation_id,
          serverName: server.name,
        })
      }
      disabled={gateway.reconnectPending}
    >
      <Key size={12} /> Reconnect your account
    </Button>
  ) : (
    <Button
      variant="solid"
      size="2"
      onClick={() =>
        // Custom servers and api-key templates collect credentials first;
        // plain OAuth templates go straight to the browser round-trip.
        gatewayConnectNeedsCredentials(server)
          ? setConnectOpen(true)
          : gateway.connect({ server })
      }
    >
      <Key size={12} /> Connect your account
    </Button>
  );

  const handleConnectSubmit = (credentials: GatewayConnectCredentials) => {
    gateway.connect({ server, credentials });
    setConnectOpen(false);
  };

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <BackButton onNavigate={onNavigate} />

      {/* Hero */}
      <Flex align="start" gap="3">
        <ServerIcon
          iconDomain={template?.icon_domain}
          serverUrl={server.url}
          size={56}
        />
        <Flex direction="column" gap="1" className="min-w-0 flex-1">
          <Flex align="center" gap="2">
            <Text truncate className="font-bold text-xl">
              {server.name}
            </Text>
            {isAdmin && !server.is_team_enabled && (
              <Badge color="gray" variant="soft" size="1">
                Off
              </Badge>
            )}
          </Flex>
          {server.description && (
            <Text color="gray" className="text-sm">
              {server.description}
            </Text>
          )}
          <Flex gap="3" align="center" mt="1">
            {server.created_by && (
              <Text color="gray" className="flex items-center gap-1 text-xs">
                <User size={12} /> {gatewayUserName(server.created_by)}
              </Text>
            )}
            {server.docs_url && (
              <a
                href={server.docs_url}
                target="_blank"
                rel="noreferrer noopener"
                className="flex items-center gap-1 text-accent-11 text-xs hover:underline"
              >
                <ArrowUpRight size={11} /> Docs
              </a>
            )}
          </Flex>
        </Flex>
        <Flex direction="column" align="end" gap="2" className="shrink-0">
          {(deletesForEveryone || deleteInstallationId) && (
            <Tooltip content="Delete server">
              <IconButton
                variant="ghost"
                color="red"
                size="2"
                aria-label="Delete server"
                onClick={() => setDeleteServerOpen(true)}
              >
                <Trash size={14} />
              </IconButton>
            </Tooltip>
          )}
          {yourConnection && (
            <Tooltip
              content={
                selfEnabled
                  ? "Disable this server for you"
                  : "Enable this server for you"
              }
            >
              {/* Tooltip stamps its own data-state on its child, which would
                  overwrite the Switch's checked/unchecked state and leave the
                  track stuck on the accent color. Give it a span to stamp. */}
              <span className="inline-flex">
                <Switch
                  size="1"
                  checked={selfEnabled}
                  onCheckedChange={(enabled) =>
                    gateway.toggleYourConnection({
                      installationId: yourConnection.installation_id,
                      enabled,
                    })
                  }
                />
              </span>
            </Tooltip>
          )}
          {yourConnection ? (
            <Flex direction="column" align="end" gap="2">
              {!deletesForEveryone && !deleteInstallationId && (
                <Button
                  variant="ghost"
                  color="gray"
                  size="2"
                  disabled={gateway.disconnectPending}
                  onClick={() =>
                    gateway.disconnect({
                      installationId: yourConnection.installation_id,
                      serverName: server.name,
                    })
                  }
                >
                  <X size={12} /> Disconnect
                </Button>
              )}
              {needsReconnect && connectButton}
            </Flex>
          ) : (
            connectButton
          )}
        </Flex>
      </Flex>

      <Separator size="4" />

      {/* Your connection exists but you switched it off for yourself. */}
      {yourConnection && !selfEnabled && (
        <Flex
          align="start"
          gap="3"
          className="rounded-md border border-(--accent-6) bg-(--accent-2) p-3"
        >
          <Flex
            align="center"
            justify="center"
            className="h-[32px] w-[32px] shrink-0 rounded-full bg-(--accent-4) text-accent-11"
          >
            <Key size={15} />
          </Flex>
          <Flex direction="column" gap="1">
            <Text className="font-medium text-sm">Disabled for you</Text>
            <Text color="gray" className="text-[13px]">
              {server.name} tools won't be offered to you until you turn it back
              on.
            </Text>
          </Flex>
        </Flex>
      )}

      {(isAdmin || canManageAgentAccess) && (
        <AccessSection
          server={server}
          gateway={gateway}
          isAdmin={isAdmin}
          currentUserId={currentUser?.id ?? null}
          accessPending={serviceAccounts.setAccessPending}
          onShareWithAgent={() => setGiveAccessOpen(true)}
          onSetMemberAccess={(userId, name, enabled) =>
            members.setMemberAccess({
              userId,
              serverId: server.id,
              enabled,
              successMessage: enabled
                ? `${name} can now use ${server.name}`
                : `${name} can no longer use ${server.name}`,
            })
          }
          onSetAgentScope={(accountId, name, scope) =>
            serviceAccounts.setAccess({
              accountId,
              serverId: server.id,
              enabled: true,
              scope,
              successMessage: agentShareMessage(server.name, name, scope),
            })
          }
          onRevokeAgent={(accountId, name) =>
            serviceAccounts.setAccess({
              accountId,
              serverId: server.id,
              enabled: false,
              successMessage: `${name} no longer has access to your ${server.name} connection`,
            })
          }
        />
      )}

      {/* Tools */}
      <Flex align="center" justify="between" wrap="wrap" gap="2" mt="2">
        <Flex align="center" gap="2">
          <Text className="font-medium text-base">Tools</Text>
          <Badge color="gray" variant="soft" size="1">
            {tools.policies.length}
          </Badge>
          <Flex gap="2">
            {counts.approved > 0 && (
              <Badge color="green" variant="soft" size="1">
                {counts.approved} Always Allow
              </Badge>
            )}
            {counts.needs_approval > 0 && (
              <Badge color="amber" variant="soft" size="1">
                {counts.needs_approval} Needs Approval
              </Badge>
            )}
            {counts.do_not_use > 0 && (
              <Badge color="red" variant="soft" size="1">
                {counts.do_not_use} blocked
              </Badge>
            )}
          </Flex>
        </Flex>
        <Flex align="center" gap="2">
          {!isAdmin && scopeEditable && scopes.length <= 1 && (
            <BulkTrio
              label="Set all"
              filtered={hasToolSearch}
              disabled={tools.setAllPending || bulkEditableCount === 0}
              allowNeedsApproval={!agentScope}
              onSet={setBulkPolicy}
            />
          )}
          {!showScopeBar && refreshInstallationId && (
            <RefreshToolsButton
              pending={tools.refreshPending}
              onRefresh={() => tools.refresh(refreshInstallationId)}
            />
          )}
        </Flex>
      </Flex>

      {showScopeBar && (
        <Flex
          align="center"
          gap="2"
          wrap="wrap"
          className="rounded-md border border-gray-5 bg-gray-2 px-3 py-2"
        >
          <Text color="gray" className="text-xs">
            Policy for
          </Text>
          {scopes.map((entry) => {
            const active = sameScope(entry, scope);
            return (
              <Button
                key={`${entry.scopeType}:${entry.scopeUserId ?? ""}:${entry.scopeServiceAccountId ?? ""}`}
                variant={active ? "solid" : "surface"}
                color={active ? undefined : "gray"}
                size="1"
                radius="full"
                onClick={() => {
                  setScope(entry);
                  setToolsExpanded(false);
                }}
              >
                {entry.scopeType === "agent" ? (
                  <Robot size={11} />
                ) : entry.scopeType === "team" ? (
                  <Users size={11} />
                ) : (
                  <User size={11} />
                )}
                {entry.label}
              </Button>
            );
          })}
          <div className="ml-auto flex items-center gap-1">
            <BulkTrio
              label={`Set all for ${scope.label}`}
              filtered={hasToolSearch}
              disabled={tools.setAllPending || bulkEditableCount === 0}
              allowNeedsApproval={!agentScope}
              onSet={setBulkPolicy}
            />
            {refreshInstallationId && (
              <RefreshToolsButton
                pending={tools.refreshPending}
                onRefresh={() => tools.refresh(refreshInstallationId)}
              />
            )}
          </div>
        </Flex>
      )}

      {tools.policies.length > 5 && (
        <TextField.Root
          value={toolSearch}
          onChange={(event) => {
            setToolSearch(event.target.value);
            setToolsExpanded(false);
          }}
          placeholder="Search tools..."
          size="2"
        >
          <TextField.Slot>
            <MagnifyingGlass size={14} />
          </TextField.Slot>
          {toolSearch && (
            <TextField.Slot>
              <IconButton
                variant="ghost"
                size="1"
                aria-label="Clear tool search"
                onClick={() => {
                  setToolSearch("");
                  setToolsExpanded(false);
                }}
              >
                <X size={12} />
              </IconButton>
            </TextField.Slot>
          )}
        </TextField.Root>
      )}

      {tools.policiesLoading && tools.policies.length === 0 ? (
        <Flex align="center" justify="center" py="6">
          <Spinner size="2" />
        </Flex>
      ) : tools.policies.length === 0 ? (
        <Flex
          direction="column"
          align="center"
          gap="1"
          py="6"
          className="rounded border border-gray-6 border-dashed"
        >
          <Text className="font-medium text-sm">No tools discovered yet.</Text>
          <Text color="gray" className="text-[13px]">
            {refreshInstallationId
              ? "This server listed no tools. Refresh to try again."
              : "Connect your account to list this server's tools."}
          </Text>
        </Flex>
      ) : filteredPolicies.length === 0 ? (
        <Flex align="center" justify="center" py="4">
          <Text color="gray" className="text-sm">
            No tools match &ldquo;{toolSearch}&rdquo;
          </Text>
        </Flex>
      ) : (
        <Flex direction="column" gap="2">
          {displayedPolicies.map((policy) => (
            <GatewayToolRow
              key={policy.tool_name}
              policy={policy}
              editable={scopeEditable && !policy.locked}
              teamScope={scope.scopeType === "team"}
              agentScope={agentScope}
              onChange={(state) =>
                tools.setPolicy({ toolName: policy.tool_name, state })
              }
            />
          ))}
          {filteredPolicies.length > TOOL_PREVIEW_LIMIT && (
            <button
              type="button"
              className="w-full px-3 py-2 text-center font-medium text-gray-11 text-xs transition-colors hover:bg-gray-2 hover:text-gray-12"
              onClick={() => setToolsExpanded((expanded) => !expanded)}
            >
              {toolsExpanded ? "View less" : "View more"}
            </button>
          )}
        </Flex>
      )}

      {connectOpen && (
        <GatewayConnectDialog
          open
          serverName={server.name}
          fixedAuthType={gatewayConnectAuthType(server)}
          onSubmit={handleConnectSubmit}
          onClose={() => setConnectOpen(false)}
        />
      )}
      <GiveAccessDialog
        open={giveAccessOpen}
        server={server}
        accounts={serviceAccounts.accounts}
        currentUserId={currentUser?.id ?? null}
        toolPolicies={teamTools.policies}
        pending={serviceAccounts.setAccessPending}
        onClose={() => setGiveAccessOpen(false)}
        onGrant={(accountId, policies, scope) => {
          const account = serviceAccounts.accounts.find(
            (entry) => entry.id === accountId,
          );
          serviceAccounts.setAccess(
            {
              accountId,
              serverId: server.id,
              enabled: true,
              scope,
              policies,
              successMessage: agentShareMessage(
                server.name,
                account?.name ?? "agent",
                scope,
              ),
            },
            { onSuccess: () => setGiveAccessOpen(false) },
          );
        }}
      />
      <GatewayDeleteServerDialog
        open={deleteServerOpen}
        serverName={server.name}
        deletesForEveryone={deletesForEveryone}
        pending={
          deletesForEveryone
            ? gateway.removeServerPending
            : gateway.disconnectPending
        }
        onOpenChange={setDeleteServerOpen}
        onConfirm={() => {
          if (deletesForEveryone) {
            gateway.removeServer(
              { serverId: server.id, serverName: server.name },
              { onSuccess: () => onNavigate({ view: "servers" }) },
            );
            return;
          }
          if (!deleteInstallationId) return;
          gateway.disconnect(
            {
              installationId: deleteInstallationId,
              serverName: server.name,
              action: "delete",
            },
            {
              onSuccess: () => onNavigate({ view: "servers" }),
            },
          );
        }}
      />
    </Flex>
  );
}

function BackButton({
  onNavigate,
}: {
  onNavigate: (route: GatewayRoute) => void;
}) {
  return (
    <Flex align="center" gap="2">
      <Button
        variant="ghost"
        color="gray"
        size="1"
        onClick={() => onNavigate({ view: "servers" })}
      >
        <ArrowLeft size={12} />
        Back to servers
      </Button>
    </Flex>
  );
}

function RefreshToolsButton({
  pending,
  onRefresh,
}: {
  pending: boolean;
  onRefresh: () => void;
}) {
  return (
    <Tooltip content="Refresh tools from server">
      <IconButton
        variant="soft"
        color="gray"
        size="1"
        aria-label="Refresh tools from server"
        disabled={pending}
        onClick={onRefresh}
      >
        {pending ? (
          <Spinner size="1" />
        ) : (
          <ArrowClockwise size={11} weight="bold" />
        )}
      </IconButton>
    </Tooltip>
  );
}

function BulkTrio({
  label,
  filtered,
  disabled,
  allowNeedsApproval,
  onSet,
}: {
  label: string;
  filtered?: boolean;
  disabled: boolean;
  allowNeedsApproval: boolean;
  onSet: (state: McpApprovalState) => void;
}) {
  return (
    <Flex align="center" gap="1">
      <Text color="gray" className="text-xs">
        {label}
      </Text>
      <Tooltip
        content={filtered ? "Always Allow filtered" : "Always Allow all"}
      >
        <IconButton
          variant="soft"
          color="green"
          size="1"
          disabled={disabled}
          onClick={() => onSet("approved")}
        >
          <Check size={11} weight="bold" />
        </IconButton>
      </Tooltip>
      {allowNeedsApproval && (
        <Tooltip
          content={
            filtered
              ? "Set filtered to Needs Approval"
              : "Set all to Needs Approval"
          }
        >
          <IconButton
            variant="soft"
            color="amber"
            size="1"
            disabled={disabled}
            onClick={() => onSet("needs_approval")}
          >
            <Shield size={11} weight="bold" />
          </IconButton>
        </Tooltip>
      )}
      <Tooltip content={filtered ? "Block filtered" : "Block all"}>
        <IconButton
          variant="soft"
          color="red"
          size="1"
          disabled={disabled}
          onClick={() => onSet("do_not_use")}
        >
          <Prohibit size={11} weight="bold" />
        </IconButton>
      </Tooltip>
    </Flex>
  );
}

interface AccessSectionProps {
  server: McpGatewayServer;
  gateway: ReturnType<typeof useGatewayServers>;
  isAdmin: boolean;
  currentUserId: number | null;
  /** True while any agent-access mutation is in flight. */
  accessPending: boolean;
  onShareWithAgent: () => void;
  onSetMemberAccess: (
    userId: number,
    firstName: string,
    enabled: boolean,
  ) => void;
  onSetAgentScope: (
    accountId: string,
    name: string,
    scope: McpAgentGrantScope,
  ) => void;
  onRevokeAgent: (accountId: string, name: string) => void;
}

function AccessSection({
  server,
  gateway,
  isAdmin,
  currentUserId,
  accessPending,
  onShareWithAgent,
  onSetMemberAccess,
  onSetAgentScope,
  onRevokeAgent,
}: AccessSectionProps) {
  const yourInstallationId = server.your_connection?.installation_id;

  return (
    <Flex direction="column" gap="2">
      <Text className="font-medium text-base">Access</Text>

      {isAdmin && (
        <>
          <Flex
            align="center"
            justify="between"
            gap="3"
            className="rounded-md border border-gray-5 bg-gray-2 p-3"
          >
            <div>
              <Text as="div" className="font-medium text-sm">
                Enabled for your organization
              </Text>
              <Text as="div" color="gray" className="text-[13px]">
                {server.is_team_enabled
                  ? `Anyone in your organization can find and use ${server.name}. Each person connects with their own account.`
                  : `${server.name} is turned off for everyone in your organization.`}
              </Text>
            </div>
            <Switch
              checked={server.is_team_enabled}
              onCheckedChange={(enabled) => {
                gateway.updateServer(
                  {
                    serverId: server.id,
                    updates: { is_team_enabled: enabled },
                  },
                  {
                    onSuccess: () => {
                      if (enabled)
                        toast.success(`${server.name} enabled for the team`);
                      else toast.info(`${server.name} disabled`);
                    },
                  },
                );
              }}
            />
          </Flex>

          <Flex align="center" gap="2" mt="1" className="tracking-[0.06em]">
            <Text
              color="gray"
              className="font-medium text-xs uppercase leading-none"
            >
              People connected
            </Text>
            <Badge color="gray" variant="soft" size="1">
              {server.connections.length}
            </Badge>
          </Flex>
          {server.connections.length === 0 ? (
            <Text color="gray" className="px-1 text-[13px] italic">
              No one has connected yet.
            </Text>
          ) : (
            <div className="overflow-hidden rounded-md border border-gray-5 bg-gray-2">
              {server.connections.map((connection) => {
                const isYou = connection.installation_id === yourInstallationId;
                const accessRevoked = server.revoked_user_ids.includes(
                  connection.user.id,
                );
                const usedAgo = formatAgo(connection.last_used_at);
                return (
                  <Flex
                    key={connection.installation_id}
                    align="center"
                    gap="3"
                    className={`group border-gray-5 border-b px-3 py-2 last:border-b-0 ${
                      accessRevoked ? "bg-gray-2 opacity-60" : ""
                    }`}
                  >
                    <UserAvatar user={connection.user} size="sm" />
                    <Flex direction="column" className="min-w-0 flex-1">
                      <Flex align="center" gap="2">
                        <Text truncate className="font-medium text-sm">
                          {gatewayUserName(connection.user)}
                        </Text>
                        {isYou && (
                          <Badge
                            color="indigo"
                            variant="soft"
                            size="1"
                            className="px-1 py-0 text-[10px] leading-4"
                          >
                            You
                          </Badge>
                        )}
                      </Flex>
                      <Text color="gray" truncate className="text-xs">
                        {connection.user.email}
                      </Text>
                    </Flex>
                    {!isYou && (
                      <Button
                        variant="ghost"
                        color={accessRevoked ? "gray" : "red"}
                        size="1"
                        className="opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                        onClick={() =>
                          onSetMemberAccess(
                            connection.user.id,
                            gatewayUserName(connection.user).split(" ")[0],
                            accessRevoked,
                          )
                        }
                      >
                        {accessRevoked ? (
                          <>
                            <Check size={11} /> Restore
                          </>
                        ) : (
                          <>
                            <X size={11} /> Revoke
                          </>
                        )}
                      </Button>
                    )}
                    <Flex align="center" gap="2" className="shrink-0">
                      <span
                        className={`h-[6px] w-[6px] rounded-full ${
                          accessRevoked
                            ? "bg-gray-8"
                            : connection.needs_reauth
                              ? "bg-(--red-9)"
                              : connection.pending_oauth
                                ? "bg-(--amber-9)"
                                : "bg-(--green-9)"
                        }`}
                      />
                      <Text color="gray" className="text-xs">
                        {accessRevoked
                          ? "Access revoked"
                          : connection.needs_reauth
                            ? "Needs reauth"
                            : connection.pending_oauth
                              ? "Finishing setup"
                              : `Connected${usedAgo ? ` · used ${usedAgo}` : ""}`}
                      </Text>
                    </Flex>
                  </Flex>
                );
              })}
            </div>
          )}
        </>
      )}

      <Flex align="center" gap="2" mt="4" className="tracking-[0.06em]">
        <Text
          color="gray"
          className="font-medium text-xs uppercase leading-none"
        >
          Agents
        </Text>
        <Badge color="gray" variant="soft" size="1">
          {server.agents.length}
        </Badge>
        <Button
          variant="ghost"
          color="gray"
          size="1"
          className="ml-auto"
          onClick={onShareWithAgent}
        >
          <Plus size={12} /> Share access with an agent
        </Button>
      </Flex>
      {server.agents.length === 0 ? (
        <Text color="gray" className="px-1 text-[13px] italic">
          No agents have access. Share a connection available to you and choose
          which {server.name} tools the agent may call.
        </Text>
      ) : (
        <div className="rounded-md border border-gray-5 bg-gray-2">
          {server.agents.map((agent) => {
            const isYourShare = agent.user.id === currentUserId;
            const teamShared = agent.scope === "team";
            return (
              <Flex
                key={`${agent.service_account_id}:${agent.user.id}`}
                align="center"
                gap="3"
                className="group border-gray-5 border-b px-3 py-2 last:border-b-0"
              >
                <RobotAvatar />
                <Flex direction="column" className="min-w-0 flex-1">
                  <Text truncate className="font-medium text-sm">
                    {agent.name}
                  </Text>
                  <Text color="gray" truncate className="text-xs">
                    <span className="font-mono">{agent.handle}</span>
                    {` · shared ${teamShared ? "to the team " : ""}by ${
                      isYourShare ? "you" : gatewayUserName(agent.user)
                    }`}
                  </Text>
                </Flex>
                {isYourShare && (
                  <AgentScopeToggle
                    value={agent.scope}
                    disabled={accessPending}
                    onChange={(scope) =>
                      onSetAgentScope(
                        agent.service_account_id,
                        agent.name,
                        scope,
                      )
                    }
                  />
                )}
                {/* Revoking removes only the caller's own share, so it is
                    offered only on rows backed by the caller's connection. */}
                {isYourShare && (
                  <Button
                    variant="ghost"
                    color="red"
                    size="1"
                    className="opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                    onClick={() =>
                      onRevokeAgent(agent.service_account_id, agent.name)
                    }
                  >
                    <X size={11} /> Revoke
                  </Button>
                )}
                <Flex align="center" gap="2" className="shrink-0">
                  <span
                    className={`h-[6px] w-[6px] rounded-full ${
                      agent.status === "active" ? "bg-(--green-9)" : "bg-gray-8"
                    }`}
                  />
                  <Text color="gray" className="text-xs">
                    {agent.status === "active"
                      ? `Active${
                          formatAgo(agent.last_active_at)
                            ? ` ${formatAgo(agent.last_active_at)}`
                            : ""
                        }`
                      : "Paused"}
                  </Text>
                </Flex>
              </Flex>
            );
          })}
        </div>
      )}
    </Flex>
  );
}
