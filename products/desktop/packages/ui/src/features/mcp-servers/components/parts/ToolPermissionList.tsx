import {
  ArrowClockwise,
  Check,
  MagnifyingGlass,
  Prohibit,
  Shield,
  X,
} from "@phosphor-icons/react";
import type {
  McpApprovalState,
  McpInstallationTool,
} from "@posthog/api-client/posthog-client";
import {
  countActiveTools,
  countToolsByApproval,
  filterToolsByName,
  sortToolsForDisplay,
} from "@posthog/core/mcp-servers/toolDerivation";
import { ToolPolicyToggle } from "@posthog/ui/features/mcp-servers/components/parts/ToolPolicyToggle";
import { ToolRow } from "@posthog/ui/features/mcp-servers/components/parts/ToolRow";
import {
  Badge,
  Flex,
  IconButton,
  Separator,
  Spinner,
  Text,
  TextField,
  Tooltip,
} from "@radix-ui/themes";
import { useMemo, useState } from "react";

/**
 * A top-level approval mode (the segmented Default control). Optional — present
 * only when the consumer has a notion of one mode every tool inherits, like the
 * agent-specific case where unset tools fall back to a connection-wide default.
 */
export interface ToolPermissionDefaultControl {
  value: McpApprovalState;
  onChange: (value: McpApprovalState) => void;
  /** Inline label beside the toggle. Defaults to "Default". */
  label?: string;
}

/** Bulk "Set all" affordance — writes every (or every filtered) tool at once. */
export interface ToolPermissionBulkControl {
  /** `tools` is the filtered subset when a search is active, else undefined (all). */
  onSetAll: (state: McpApprovalState, tools?: McpInstallationTool[]) => void;
  pending?: boolean;
}

/** Re-discover the server's tool catalog. */
export interface ToolPermissionRefreshControl {
  onRefresh: () => void;
  pending?: boolean;
}

/** Reveal tools the server has dropped since they were last seen. */
export interface ToolPermissionRemovedControl {
  count: number;
  show: boolean;
  onToggle: () => void;
}

export interface ToolPermissionListProps {
  /**
   * Tools to render. Each `approval_state` is the effective state to *display*;
   * how that state is derived (a persisted installation value, or an override
   * resolved against a default) is the parent's concern.
   */
  tools: McpInstallationTool[];
  /** Per-tool change. The parent decides what persisting it means. */
  onSetTool: (toolName: string, state: McpApprovalState) => void;
  isLoading?: boolean;
  /** Disable every control (read-only view, or an in-flight save). */
  disabled?: boolean;
  /** Section heading. Defaults to "Tools". */
  heading?: string;
  /** Top-level approval mode shown in the header. */
  defaultControl?: ToolPermissionDefaultControl;
  /** "Set all" icon buttons shown in the header. */
  bulk?: ToolPermissionBulkControl;
  /** Refresh-from-server icon button shown in the header. */
  refresh?: ToolPermissionRefreshControl;
  /** Removed-tools reveal shown beneath the list. */
  removed?: ToolPermissionRemovedControl;
  /** Empty-state copy when no tools are present. */
  emptyTitle?: string;
  emptyHint?: string;
  /** Show the search field once the list exceeds this length. Defaults to 5. */
  searchThreshold?: number;
}

/**
 * Searchable, expandable tool-permission list with optional default-mode, bulk,
 * refresh, and removed-tools controls. Purely presentational: it owns search and
 * expand state only — every permission decision is delegated to the parent via
 * callbacks, so the same component serves PostHog's global MCP-server
 * config and an agent's per-server overrides without knowing which it is.
 */
export function ToolPermissionList({
  tools,
  onSetTool,
  isLoading,
  disabled,
  heading = "Tools",
  defaultControl,
  bulk,
  refresh,
  removed,
  emptyTitle = "No tools discovered yet.",
  emptyHint = "Try refreshing, or check that the server is online.",
  searchThreshold = 5,
}: ToolPermissionListProps) {
  const [toolSearch, setToolSearch] = useState("");

  const counts = useMemo(() => countToolsByApproval(tools), [tools]);
  const visibleTools = useMemo(() => sortToolsForDisplay(tools), [tools]);
  const filteredTools = useMemo(
    () => filterToolsByName(visibleTools, toolSearch),
    [visibleTools, toolSearch],
  );

  const bulkDisabled = disabled || bulk?.pending || filteredTools.length === 0;
  const bulkTargets = toolSearch ? filteredTools : undefined;

  return (
    <Flex direction="column" gap="3" className="min-w-0">
      <Flex align="center" justify="between" wrap="wrap" gap="2">
        <Flex align="center" gap="3">
          <Text className="font-medium text-base">{heading}</Text>
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
          {defaultControl ? (
            <Flex gap="2" align="center">
              <Text color="gray" className="text-[13px]">
                {defaultControl.label ?? "Default"}:
              </Text>
              <ToolPolicyToggle
                value={defaultControl.value}
                onChange={defaultControl.onChange}
                disabled={disabled}
              />
            </Flex>
          ) : null}
          {bulk ? (
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
                  disabled={bulkDisabled}
                  onClick={() => bulk.onSetAll("approved", bulkTargets)}
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
                  disabled={bulkDisabled}
                  onClick={() => bulk.onSetAll("needs_approval", bulkTargets)}
                >
                  <Shield size={12} weight="bold" />
                </IconButton>
              </Tooltip>
              <Tooltip content={toolSearch ? "Block filtered" : "Block all"}>
                <IconButton
                  variant="soft"
                  color="red"
                  size="1"
                  disabled={bulkDisabled}
                  onClick={() => bulk.onSetAll("do_not_use", bulkTargets)}
                >
                  <Prohibit size={12} weight="bold" />
                </IconButton>
              </Tooltip>
            </Flex>
          ) : null}
          {refresh ? (
            <>
              {defaultControl || bulk ? (
                <Separator orientation="vertical" />
              ) : null}
              <Tooltip content="Refresh tools from server">
                <IconButton
                  variant="soft"
                  color="gray"
                  size="1"
                  disabled={disabled || refresh.pending}
                  onClick={refresh.onRefresh}
                >
                  {refresh.pending ? (
                    <Spinner size="1" />
                  ) : (
                    <ArrowClockwise size={12} weight="bold" />
                  )}
                </IconButton>
              </Tooltip>
            </>
          ) : null}
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
          {refresh?.pending ? (
            <Spinner size="1" />
          ) : (
            <>
              <Text className="font-medium text-sm">{emptyTitle}</Text>
              <Text color="gray" className="text-[13px]">
                {emptyHint}
              </Text>
            </>
          )}
        </Flex>
      ) : (
        <Flex direction="column" gap="2">
          {visibleTools.length > searchThreshold && (
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
                  onSetTool(tool.tool_name, approval_state)
                }
              />
            ))
          )}
        </Flex>
      )}

      {removed && removed.count > 0 && (
        <Flex justify="end">
          <button
            type="button"
            onClick={removed.onToggle}
            className="text-gray-11 text-xs hover:underline"
          >
            {removed.show ? "Hide" : "Show"} removed tools ({removed.count})
          </button>
        </Flex>
      )}
    </Flex>
  );
}
