import {
  ArrowClockwise,
  ArrowLeft,
  ArrowUpRight,
  Check,
  DownloadSimple,
  MagnifyingGlass,
  Prohibit,
  Shield,
  Trash,
  X,
} from "@phosphor-icons/react";
import type {
  McpRecommendedServer,
  McpServerInstallation,
} from "@posthog/api-client/posthog-client";
import { resolveServerDetails } from "@posthog/core/mcp-servers/resolveServerName";
import { getInstallationStatus } from "@posthog/core/mcp-servers/status";
import {
  countActiveTools,
  countRemovedTools,
  countToolsByApproval,
  filterToolsByName,
  sortToolsForDisplay,
} from "@posthog/core/mcp-servers/toolDerivation";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import {
  STATUS_COLORS,
  STATUS_LABELS,
} from "@posthog/ui/features/mcp-servers/components/parts/statusBadge";
import { ToolRow } from "@posthog/ui/features/mcp-servers/components/parts/ToolRow";
import { useMcpInstallationTools } from "@posthog/ui/features/mcp-servers/hooks/useMcpInstallationTools";
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

interface ServerDetailViewProps {
  installation: McpServerInstallation | null;
  template: McpRecommendedServer | null;
  isEnabled: boolean;
  isInstalling: boolean;
  isReauthorizing: boolean;
  onBack: () => void;
  onConnect: () => void;
  onReauthorize: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onUninstall: () => void;
}

export function ServerDetailView({
  installation,
  template,
  isEnabled,
  isInstalling,
  isReauthorizing,
  onBack,
  onConnect,
  onReauthorize,
  onToggleEnabled,
  onUninstall,
}: ServerDetailViewProps) {
  const [showRemoved, setShowRemoved] = useState(false);
  const [toolSearch, setToolSearch] = useState("");

  const { name, description, docsUrl, iconDomain, serverUrl, authType } =
    resolveServerDetails(installation, template);

  const {
    tools,
    isLoading,
    setToolApproval,
    setBulkApproval,
    bulkPending,
    refresh,
    refreshPending,
  } = useMcpInstallationTools(installation?.id ?? null, {
    includeRemoved: showRemoved,
    autoRefreshIfEmpty: true,
  });

  const status = installation ? getInstallationStatus(installation) : null;
  const statusLabel = status ? STATUS_LABELS[status] : "Not installed";
  const statusColor = status ? STATUS_COLORS[status] : "gray";

  const counts = useMemo(() => countToolsByApproval(tools), [tools]);

  const visibleTools = useMemo(() => sortToolsForDisplay(tools), [tools]);

  const filteredTools = useMemo(
    () => filterToolsByName(visibleTools, toolSearch),
    [visibleTools, toolSearch],
  );

  const removedCount = countRemovedTools(tools);

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <Flex align="center" gap="2">
        <Button variant="ghost" color="gray" size="1" onClick={onBack}>
          <ArrowLeft size={12} />
          Back
        </Button>
      </Flex>

      <Flex align="start" gap="3">
        <ServerIcon iconDomain={iconDomain} serverUrl={serverUrl} size={56} />
        <Flex direction="column" gap="1" className="min-w-0 flex-1">
          <Flex align="center" gap="2">
            <Text truncate className="font-bold text-xl">
              {name}
            </Text>
            {installation && (
              <Badge color={statusColor} variant="soft">
                {statusLabel}
              </Badge>
            )}
          </Flex>
          {description && (
            <Text color="gray" className="text-sm">
              {description}
            </Text>
          )}
          <Flex gap="3" align="center" mt="1">
            {authType && (
              <Badge color="gray" variant="outline" size="1">
                {authType === "oauth" ? "OAuth" : "API key"}
              </Badge>
            )}
            {docsUrl && (
              <a
                href={docsUrl}
                target="_blank"
                rel="noreferrer noopener"
                className="flex items-center gap-1 text-accent-11 text-xs hover:underline"
              >
                <ArrowUpRight size={11} />
                Docs
              </a>
            )}
          </Flex>
        </Flex>
        <Flex direction="column" align="end" gap="2" className="shrink-0">
          <Flex gap="2" align="center">
            {installation ? (
              status === "needs_reauth" || status === "pending_oauth" ? (
                <Button
                  variant="solid"
                  size="2"
                  onClick={onReauthorize}
                  disabled={isReauthorizing}
                >
                  {isReauthorizing ? <Spinner size="1" /> : null}
                  Reconnect
                </Button>
              ) : null
            ) : (
              <Button
                variant="solid"
                size="2"
                onClick={onConnect}
                disabled={isInstalling}
              >
                {isInstalling ? (
                  <Spinner size="1" />
                ) : (
                  <DownloadSimple size={12} />
                )}
                Connect
              </Button>
            )}
            {installation && (
              <Tooltip content="Remove server">
                <IconButton
                  variant="ghost"
                  color="red"
                  size="2"
                  onClick={onUninstall}
                >
                  <Trash size={14} />
                </IconButton>
              </Tooltip>
            )}
          </Flex>
          {installation && status === "connected" && (
            <Flex align="center" gap="2">
              <Switch
                size="1"
                checked={isEnabled}
                onCheckedChange={onToggleEnabled}
              />
            </Flex>
          )}
        </Flex>
      </Flex>

      {installation && status === "connected" && (
        <>
          <Separator size="4" />
          <Flex align="center" justify="between" wrap="wrap" gap="2">
            <Flex align="center" gap="3">
              <Text className="font-medium text-base">Tools</Text>
              <Badge color="gray" variant="soft" size="1">
                {countActiveTools(tools)}
              </Badge>
              <Flex gap="2">
                {counts.approved ? (
                  <Badge color="green" variant="soft" size="1">
                    {counts.approved} approved
                  </Badge>
                ) : null}
                {counts.needs_approval ? (
                  <Badge color="amber" variant="soft" size="1">
                    {counts.needs_approval} need approval
                  </Badge>
                ) : null}
                {counts.do_not_use ? (
                  <Badge color="red" variant="soft" size="1">
                    {counts.do_not_use} blocked
                  </Badge>
                ) : null}
              </Flex>
            </Flex>
            <Flex gap="2" align="center">
              <Text color="gray" className="text-[13px]">
                Set all:
              </Text>
              <Tooltip
                content={toolSearch ? "Approve filtered" : "Approve all"}
              >
                <IconButton
                  variant="soft"
                  color="green"
                  size="1"
                  disabled={bulkPending || filteredTools.length === 0}
                  onClick={() =>
                    setBulkApproval(
                      "approved",
                      toolSearch ? filteredTools : undefined,
                    )
                  }
                >
                  <Check size={12} weight="bold" />
                </IconButton>
              </Tooltip>
              <Tooltip
                content={
                  toolSearch
                    ? "Require approval for filtered"
                    : "Require approval for all"
                }
              >
                <IconButton
                  variant="soft"
                  color="amber"
                  size="1"
                  disabled={bulkPending || filteredTools.length === 0}
                  onClick={() =>
                    setBulkApproval(
                      "needs_approval",
                      toolSearch ? filteredTools : undefined,
                    )
                  }
                >
                  <Shield size={12} weight="bold" />
                </IconButton>
              </Tooltip>
              <Tooltip content={toolSearch ? "Block filtered" : "Block all"}>
                <IconButton
                  variant="soft"
                  color="red"
                  size="1"
                  disabled={bulkPending || filteredTools.length === 0}
                  onClick={() =>
                    setBulkApproval(
                      "do_not_use",
                      toolSearch ? filteredTools : undefined,
                    )
                  }
                >
                  <Prohibit size={12} weight="bold" />
                </IconButton>
              </Tooltip>
              <Separator orientation="vertical" />
              <Tooltip content="Refresh tools from server">
                <IconButton
                  variant="soft"
                  color="gray"
                  size="1"
                  disabled={refreshPending}
                  onClick={refresh}
                >
                  {refreshPending ? (
                    <Spinner size="1" />
                  ) : (
                    <ArrowClockwise size={12} weight="bold" />
                  )}
                </IconButton>
              </Tooltip>
            </Flex>
          </Flex>

          {isLoading ? (
            <Flex align="center" justify="center" py="6">
              <Spinner size="2" />
            </Flex>
          ) : visibleTools.length === 0 ? (
            <Flex
              align="center"
              justify="center"
              direction="column"
              gap="1"
              py="6"
              className="rounded border border-gray-6 border-dashed"
            >
              {refreshPending ? (
                <Spinner size="1" />
              ) : (
                <>
                  <Text className="font-medium text-sm">
                    No tools discovered yet.
                  </Text>
                  <Text color="gray" className="text-[13px]">
                    Try refreshing, or check that the server is online.
                  </Text>
                </>
              )}
            </Flex>
          ) : (
            <Flex direction="column" gap="2">
              {visibleTools.length > 5 && (
                <TextField.Root
                  value={toolSearch}
                  onChange={(e) => setToolSearch(e.target.value)}
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
                        onClick={() => setToolSearch("")}
                      >
                        <X size={12} />
                      </IconButton>
                    </TextField.Slot>
                  )}
                </TextField.Root>
              )}
              {filteredTools.length === 0 ? (
                <Flex align="center" justify="center" py="4">
                  <Text color="gray" className="text-sm">
                    No tools match &ldquo;{toolSearch}&rdquo;
                  </Text>
                </Flex>
              ) : (
                filteredTools.map((tool) => (
                  <ToolRow
                    key={tool.tool_name}
                    tool={tool}
                    onChange={(approval_state) =>
                      setToolApproval({
                        toolName: tool.tool_name,
                        approval_state,
                      })
                    }
                  />
                ))
              )}
            </Flex>
          )}

          {removedCount > 0 && (
            <Flex justify="end">
              <Button
                variant="ghost"
                color="gray"
                size="1"
                onClick={() => setShowRemoved((v) => !v)}
              >
                {showRemoved ? "Hide" : "Show"} removed tools ({removedCount})
              </Button>
            </Flex>
          )}
        </>
      )}

      {installation && status !== "connected" && (
        <Flex
          direction="column"
          align="center"
          justify="center"
          gap="2"
          py="6"
          className="rounded border border-gray-6 border-dashed"
        >
          <Text className="font-medium text-sm">
            {status === "pending_oauth"
              ? "Finish connecting to start using this server."
              : "This server needs to be reconnected."}
          </Text>
          <Text color="gray" className="text-[13px]">
            Click Reconnect above to resume the OAuth flow.
          </Text>
        </Flex>
      )}
    </Flex>
  );
}
