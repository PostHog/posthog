import {
  ArrowSquareOutIcon,
  CircleNotchIcon,
  type IconProps,
} from "@phosphor-icons/react";
import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import { Button } from "@posthog/quill";
import {
  RESPONDER_AGENT_GROUPS,
  type ResponderAgentDefinition,
  type ResponderAgentSource,
} from "@posthog/ui/features/inbox/components/responderAgentMeta";
import type { SignalSourceValues } from "@posthog/ui/features/inbox/components/SignalSourceToggles";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Box, Flex, Spinner, Switch, Text, Tooltip } from "@radix-ui/themes";
import { type ComponentType, memo, useCallback } from "react";

type AgentRosterStatus = "standby" | "watching" | "syncing" | "sync_failed";

function resolveAgentStatus(
  armed: boolean,
  syncStatus: SignalSourceConfig["status"] | undefined,
): AgentRosterStatus {
  if (!armed) return "standby";
  if (syncStatus === "running") return "syncing";
  if (syncStatus === "failed") return "sync_failed";
  return "watching";
}

const STATUS_BADGE: Record<
  AgentRosterStatus,
  { label: string; variant: "default" | "info" | "success" | "destructive" }
> = {
  standby: { label: "Standby", variant: "default" },
  watching: { label: "Watching", variant: "success" },
  syncing: { label: "Syncing", variant: "info" },
  sync_failed: { label: "Sync failed", variant: "destructive" },
};

const AGENT_CARD_BASE_CLASS =
  "rounded-(--radius-3) border bg-(--color-panel-solid) p-3 transition duration-150";
const AGENT_CARD_INTERACTIVE_IDLE_CLASS =
  "cursor-pointer hover:border-(--gray-6) hover:bg-(--gray-2) hover:shadow-sm";
const AGENT_CARD_INTERACTIVE_ARMED_CLASS =
  "cursor-pointer hover:border-(--accent-7) hover:bg-(--accent-2) hover:shadow-sm";

interface ResponderAgentRosterProps {
  value: SignalSourceValues;
  onToggle: (source: ResponderAgentSource, enabled: boolean) => void;
  disabled?: boolean;
  sourceStates?: Partial<
    Record<
      ResponderAgentSource,
      {
        requiresSetup: boolean;
        loading: boolean;
        syncStatus?: SignalSourceConfig["status"];
      }
    >
  >;
  onSetup?: (source: ResponderAgentSource) => void;
  evaluationsUrl?: string;
}

export function ResponderAgentRoster({
  value,
  onToggle,
  disabled,
  sourceStates,
  onSetup,
  evaluationsUrl,
}: ResponderAgentRosterProps) {
  return (
    <Flex direction="column" gap="5">
      {RESPONDER_AGENT_GROUPS.map((group) => (
        <Flex key={group.label} direction="column" gap="2">
          <Text className="font-medium text-(--gray-9) text-[13px]">
            {group.label}
          </Text>
          <Box className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {group.agents.map((agent) => (
              <ResponderAgentCard
                key={agent.source}
                agent={agent}
                armed={value[agent.source]}
                disabled={disabled}
                state={sourceStates?.[agent.source]}
                onToggle={onToggle}
                onSetup={onSetup}
              />
            ))}
            {group.label === "PostHog data" && evaluationsUrl ? (
              <EvaluationsAgentCard evaluationsUrl={evaluationsUrl} />
            ) : null}
          </Box>
        </Flex>
      ))}
    </Flex>
  );
}

interface ResponderAgentCardProps {
  agent: ResponderAgentDefinition;
  armed: boolean;
  disabled?: boolean;
  state?: {
    requiresSetup: boolean;
    loading: boolean;
    syncStatus?: SignalSourceConfig["status"];
  };
  onToggle: (source: ResponderAgentSource, enabled: boolean) => void;
  onSetup?: (source: ResponderAgentSource) => void;
}

const ResponderAgentCard = memo(function ResponderAgentCard({
  agent,
  armed,
  disabled,
  state,
  onToggle,
  onSetup,
}: ResponderAgentCardProps) {
  const meta = getSourceProductMeta(agent.sourceProduct);
  const status = resolveAgentStatus(armed, state?.syncStatus);
  const statusBadge = STATUS_BADGE[status];
  const requiresSetup = state?.requiresSetup ?? false;
  const loading = state?.loading ?? false;
  const accentColor = meta?.color ?? "var(--accent-9)";
  const Icon = meta?.Icon;
  const isInteractive = !disabled && !loading;

  const handleCardClick = useCallback(() => {
    if (!isInteractive) return;
    if (requiresSetup) {
      onSetup?.(agent.source);
      return;
    }
    onToggle(agent.source, !armed);
  }, [agent.source, armed, isInteractive, onSetup, onToggle, requiresSetup]);

  const handleToggle = useCallback(
    (checked: boolean) => onToggle(agent.source, checked),
    [agent.source, onToggle],
  );

  return (
    <Box
      onClick={isInteractive ? handleCardClick : undefined}
      className={[
        AGENT_CARD_BASE_CLASS,
        armed ? "border-(--accent-6) bg-(--accent-2)" : "border-border",
        isInteractive
          ? armed
            ? AGENT_CARD_INTERACTIVE_ARMED_CLASS
            : AGENT_CARD_INTERACTIVE_IDLE_CLASS
          : "cursor-default",
      ].join(" ")}
    >
      <Flex align="start" justify="between" gap="3">
        <Flex align="start" gap="3" className="min-w-0 flex-1">
          <AgentIcon accentColor={accentColor} Icon={Icon} />
          <Flex direction="column" gap="1" className="min-w-0">
            <Flex align="center" gap="2" wrap="wrap">
              <Text className="font-medium text-[13px] text-gray-12">
                {agent.label}
              </Text>
              {agent.alpha ? (
                <Badge color="orange" className="text-[11px]">
                  Alpha
                </Badge>
              ) : null}
            </Flex>
            <Text className="text-[13px] text-gray-11 leading-snug">
              {agent.description}
            </Text>
            {agent.docsUrl ? (
              <Text className="text-[13px] text-gray-11">
                <a
                  href={agent.docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    window.open(agent.docsUrl, "_blank", "noopener");
                  }}
                  className="inline-flex items-center gap-1 text-(--accent-11) no-underline"
                >
                  Learn about {agent.docsLabel ?? agent.label}
                  <ArrowSquareOutIcon size={11} />
                </a>
              </Text>
            ) : null}
          </Flex>
        </Flex>

        <Flex
          direction="column"
          align="end"
          gap="2"
          className="shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          <InboxBadge variant={statusBadge.variant}>
            {statusBadge.label}
          </InboxBadge>
          {loading ? (
            <Spinner size="2" />
          ) : requiresSetup ? (
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => onSetup?.(agent.source)}
            >
              Connect
            </Button>
          ) : (
            <Switch
              checked={armed}
              onCheckedChange={handleToggle}
              disabled={disabled}
              aria-label={`Arm ${agent.label}`}
            />
          )}
        </Flex>
      </Flex>

      {armed && agent.source === "session_replay" && status === "syncing" ? (
        <Flex align="center" gap="2" className="mt-2 ml-8">
          <CircleNotchIcon
            size={14}
            className="animate-spin text-(--accent-11)"
          />
          <Text className="text-(--accent-11) text-[13px]">
            Session analysis run in progress…
          </Text>
        </Flex>
      ) : null}
    </Box>
  );
});

function AgentIcon({
  accentColor,
  Icon,
}: {
  accentColor: string;
  Icon?: ComponentType<IconProps>;
}) {
  return (
    <Flex
      align="center"
      justify="center"
      className="h-8 w-8 shrink-0 rounded-(--radius-2) ring-(--gray-6) ring-1 ring-inset"
      style={{
        backgroundColor: `color-mix(in srgb, ${accentColor} 12%, transparent)`,
      }}
    >
      {Icon ? <Icon size={18} style={{ color: accentColor }} /> : null}
    </Flex>
  );
}

const EvaluationsAgentCard = memo(function EvaluationsAgentCard({
  evaluationsUrl,
}: {
  evaluationsUrl: string;
}) {
  return (
    <Box
      onClick={() => window.open(evaluationsUrl, "_blank", "noopener")}
      className={[
        AGENT_CARD_BASE_CLASS,
        "border-border",
        AGENT_CARD_INTERACTIVE_IDLE_CLASS,
      ].join(" ")}
    >
      <Flex align="start" justify="between" gap="3">
        <Flex align="start" gap="3" className="min-w-0 flex-1">
          <AgentIcon
            accentColor="var(--purple-9)"
            Icon={getSourceProductMeta("llm_analytics")?.Icon}
          />
          <Flex direction="column" gap="1" className="min-w-0">
            <Flex align="center" gap="2" wrap="wrap">
              <Text className="font-medium text-[13px] text-gray-12">
                AI Observability
              </Text>
              <Tooltip content="This is only visible to staff users of PostHog">
                <Badge color="blue" className="text-[11px]">
                  Internal
                </Badge>
              </Tooltip>
            </Flex>
            <Text className="text-[13px] text-gray-11 leading-snug">
              Quality problems in your AI features.
            </Text>
            <Text className="text-[13px] text-gray-11">
              <a
                href="https://posthog.com/docs/ai-observability"
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  window.open(
                    "https://posthog.com/docs/ai-observability",
                    "_blank",
                    "noopener",
                  );
                }}
                className="inline-flex items-center gap-1 text-(--accent-11) no-underline"
              >
                Learn about AI observability
                <ArrowSquareOutIcon size={11} />
              </a>
            </Text>
          </Flex>
        </Flex>
        <Button
          type="button"
          variant="primary"
          size="sm"
          className="shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            window.open(evaluationsUrl, "_blank", "noopener");
          }}
        >
          Open
          <ArrowSquareOutIcon size={12} />
        </Button>
      </Flex>
    </Box>
  );
});

function ResponderAgentCardSkeleton() {
  return (
    <Box className={`${AGENT_CARD_BASE_CLASS} border-border`}>
      <Flex align="start" justify="between" gap="3">
        <Flex align="start" gap="3" className="min-w-0 flex-1">
          <Box className="h-8 w-8 shrink-0 animate-pulse rounded-(--radius-2) bg-gray-4" />
          <Flex direction="column" gap="2" className="min-w-0 flex-1">
            <Box className="h-[13px] w-[50%] animate-pulse rounded bg-gray-4" />
            <Box className="h-[11px] w-[35%] animate-pulse rounded bg-gray-3" />
            <Box className="h-[12px] w-[85%] animate-pulse rounded bg-gray-3" />
          </Flex>
        </Flex>
        <Box className="h-[22px] w-[72px] shrink-0 animate-pulse rounded bg-gray-3" />
      </Flex>
    </Box>
  );
}

export function ResponderAgentRosterSkeleton() {
  return (
    <Flex direction="column" gap="5">
      {RESPONDER_AGENT_GROUPS.map((group) => (
        <Flex key={group.label} direction="column" gap="2">
          <Box className="h-[13px] w-[100px] animate-pulse rounded bg-gray-4" />
          <Box className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {group.agents.map((agent) => (
              <ResponderAgentCardSkeleton key={agent.source} />
            ))}
          </Box>
        </Flex>
      ))}
    </Flex>
  );
}
