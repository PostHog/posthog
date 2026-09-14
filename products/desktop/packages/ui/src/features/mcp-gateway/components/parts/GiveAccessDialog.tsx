import { Check, Prohibit } from "@phosphor-icons/react";
import type {
  McpAgentGrantScope,
  McpGatewayServer,
  McpResolvedToolPolicy,
  McpServiceAccount,
  McpToolPolicyEntry,
} from "@posthog/api-client/posthog-client";
import {
  AGENT_POLICY_STATES,
  type AgentPolicyState,
  defaultAgentGrantPolicy,
  isAgentPolicyState,
} from "@posthog/core/mcp-gateway/gatewayServers";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  DialogBody,
} from "@posthog/quill";
import { AgentScopeToggle } from "@posthog/ui/features/mcp-gateway/components/parts/AgentScopeToggle";
import { RobotAvatar } from "@posthog/ui/features/mcp-gateway/components/parts/avatars";
import { ToolPolicyToggle } from "@posthog/ui/features/mcp-servers/components/parts/ToolPolicyToggle";
import { Badge, IconButton, Select, Tooltip } from "@radix-ui/themes";
import { useMemo, useState } from "react";

interface GiveAccessDialogProps {
  open: boolean;
  server: McpGatewayServer;
  /** Every service account; ones the caller already shared with are filtered out. */
  accounts: McpServiceAccount[];
  currentUserId: number | null;
  /** Team-scope rows, used for tool names and rule locks. */
  toolPolicies: McpResolvedToolPolicy[];
  pending: boolean;
  onClose: () => void;
  onGrant: (
    accountId: string,
    policies: McpToolPolicyEntry[],
    scope: McpAgentGrantScope,
  ) => void;
}

/** "Share <server> with an agent" — agent picker plus per-tool starting policies. */
export function GiveAccessDialog(props: GiveAccessDialogProps) {
  return (
    <GiveAccessDialogDraft key={props.open ? "open" : "closed"} {...props} />
  );
}

function GiveAccessDialogDraft({
  open,
  server,
  accounts,
  currentUserId,
  toolPolicies,
  pending,
  onClose,
  onGrant,
}: GiveAccessDialogProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [scope, setScope] = useState<McpAgentGrantScope>("personal");
  const [policyMap, setPolicyMap] = useState<Record<string, AgentPolicyState>>(
    {},
  );

  const selectAgent = (accountId: string) => {
    setSelectedId(accountId);
    setPolicyMap({});
  };

  // A teammate's share doesn't block the caller's own — several members may
  // each back the same agent, so only agents the caller already shared with
  // drop out of the picker.
  const available = useMemo(() => {
    const sharedByYou = new Set(
      server.agents
        .filter((agent) => agent.user.id === currentUserId)
        .map((agent) => agent.service_account_id),
    );
    return accounts.filter((account) => !sharedByYou.has(account.id));
  }, [accounts, server.agents, currentUserId]);

  const selected = available.find((account) => account.id === selectedId);

  const policyFor = (toolName: string): AgentPolicyState =>
    policyMap[toolName] ?? defaultAgentGrantPolicy(toolName);

  const setToolPolicy = (toolName: string, state: AgentPolicyState) =>
    setPolicyMap((map) => ({ ...map, [toolName]: state }));

  const bulkSet = (state: AgentPolicyState) =>
    setPolicyMap((map) => {
      const next = { ...map };
      for (const policy of toolPolicies) {
        if (policy.decided_by !== "rule") next[policy.tool_name] = state;
      }
      return next;
    });

  const grant = () => {
    if (!selected) return;
    const policies = toolPolicies
      .filter((policy) => policy.decided_by !== "rule")
      .map((policy) => ({
        tool_name: policy.tool_name,
        policy_state: policyFor(policy.tool_name),
      }));
    onGrant(selected.id, policies, scope);
  };

  return (
    <AlertDialog open={open} onOpenChange={() => undefined}>
      <AlertDialogContent className="max-w-[440px]">
        <AlertDialogHeader>
          <AlertDialogTitle>Share {server.name} with an agent</AlertDialogTitle>
          <AlertDialogDescription>
            The agent uses a connection available to you and calls {server.name}{" "}
            under the tool policies you set below.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            <Select.Root
              value={selectedId ?? undefined}
              onValueChange={selectAgent}
              disabled={pending}
            >
              <Select.Trigger placeholder="Choose an agent…" />
              <Select.Content>
                {available.map((account) => (
                  <Select.Item key={account.id} value={account.id}>
                    {account.name}{" "}
                    <span className="font-mono text-xs">{account.handle}</span>
                    {account.status === "paused" ? " (paused)" : ""}
                  </Select.Item>
                ))}
                {available.length === 0 && (
                  <p className="px-3 py-2 text-gray-10 text-sm italic">
                    You've already shared {server.name} with every agent.
                  </p>
                )}
              </Select.Content>
            </Select.Root>

            {selected && (
              <div className="flex items-center justify-between gap-3">
                <span className="text-[13px] text-gray-10">Applies to</span>
                <AgentScopeToggle
                  value={scope}
                  disabled={pending}
                  onChange={setScope}
                />
              </div>
            )}

            {selected && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <RobotAvatar size="sm" />
                    <span className="font-medium text-[10px] text-gray-10 uppercase tracking-[0.06em]">
                      Tool policy for {selected.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-gray-10 text-xs">Set all</span>
                    <Tooltip content="Always Allow all">
                      <IconButton
                        variant="soft"
                        color="green"
                        size="1"
                        disabled={pending}
                        onClick={() => bulkSet("approved")}
                      >
                        <Check size={11} weight="bold" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip content="Block all">
                      <IconButton
                        variant="soft"
                        color="red"
                        size="1"
                        disabled={pending}
                        onClick={() => bulkSet("do_not_use")}
                      >
                        <Prohibit size={11} weight="bold" />
                      </IconButton>
                    </Tooltip>
                  </div>
                </div>
                <div className="max-h-[280px] overflow-y-auto rounded border border-gray-5">
                  {toolPolicies.map((policy) => (
                    <div
                      key={policy.tool_name}
                      className="flex items-center justify-between gap-3 border-gray-5 border-b px-3 py-1.5 last:border-b-0"
                    >
                      <span className="truncate text-[12.5px]">
                        {policy.tool_name}
                      </span>
                      {policy.decided_by === "rule" ? (
                        <Badge color="gray" variant="soft" size="1">
                          Blocked by team policy
                        </Badge>
                      ) : (
                        <ToolPolicyToggle
                          value={policyFor(policy.tool_name)}
                          disabled={pending}
                          allowedStates={AGENT_POLICY_STATES}
                          onChange={(state) => {
                            if (isAgentPolicyState(state)) {
                              setToolPolicy(policy.tool_name, state);
                            }
                          }}
                        />
                      )}
                    </div>
                  ))}
                  {toolPolicies.length === 0 && (
                    <p className="px-3 py-2 text-gray-10 text-sm italic">
                      No tools discovered yet — the agent gets access as soon as
                      tools appear.
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </DialogBody>
        <AlertDialogFooter>
          <Button variant="outline" disabled={pending} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={pending}
            disabled={!selected || pending}
            onClick={grant}
          >
            {!pending && <Check size={12} weight="bold" />}
            Share access
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
