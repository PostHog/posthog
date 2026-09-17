import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  type IconProps,
} from "@phosphor-icons/react";
import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import { Button, cn, Skeleton, Switch, Text } from "@posthog/quill";
import {
  RESPONDER_AGENT_GROUPS,
  type ResponderAgentDefinition,
  type ResponderAgentSource,
} from "@posthog/ui/features/inbox/components/responderAgentMeta";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { projectUrl } from "@posthog/ui/utils/posthogLinks";
import {
  type ComponentType,
  memo,
  type ReactNode,
  useCallback,
  useState,
} from "react";

type AgentRosterStatus = "standby" | "watching" | "syncing" | "sync_failed";

/** One individually switchable thing inside a source: a scanner or a signal type. */
export interface ResponderEntity {
  id: string;
  name: string;
  detail?: string;
  kind?: string;
  enabled: boolean;
}

export interface ResponderSourceState {
  requiresSetup: boolean;
  loading: boolean;
  syncStatus?: SignalSourceConfig["status"];
  entities?: ResponderEntity[];
  /** The entity list has not arrived, so a count would read as a wrong zero. */
  entitiesLoading?: boolean;
  /** Entity ids with a switch in flight. */
  pendingEntities?: Record<string, boolean>;
}

/** The cards sit in a grid, so an unbounded list would stretch one column far past the other. */
const ENTITY_VISIBLE_LIMIT = 6;

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
  "overflow-hidden rounded-lg border bg-card transition duration-150";
const AGENT_CARD_INTERACTIVE_IDLE_CLASS = "hover:bg-muted";
const AGENT_CARD_INTERACTIVE_ARMED_CLASS =
  "hover:border-accent-7 hover:bg-accent-3";

interface ResponderAgentRosterProps {
  value: Partial<Record<ResponderAgentSource, boolean>>;
  onToggle: (source: ResponderAgentSource, enabled: boolean) => void;
  disabled?: boolean;
  sourceStates?: Partial<Record<ResponderAgentSource, ResponderSourceState>>;
  onSetup?: (source: ResponderAgentSource) => void;
  onToggleEntity?: (source: ResponderAgentSource, entityId: string) => void;
}

export function ResponderAgentRoster({
  value,
  onToggle,
  disabled,
  sourceStates,
  onSetup,
  onToggleEntity,
}: ResponderAgentRosterProps) {
  const [expanded, setExpanded] = useState<ResponderAgentSource | null>(null);

  return (
    <div className="flex flex-col gap-5">
      {RESPONDER_AGENT_GROUPS.map((group) => (
        <div key={group.label} className="flex flex-col gap-2">
          <Text className="font-medium text-muted-foreground text-xs">
            {group.label}
          </Text>
          <div className="grid grid-cols-1 items-start gap-3 sm:grid-cols-2">
            {group.agents.map((agent) => (
              <ResponderAgentCard
                key={agent.source}
                agent={agent}
                armed={value[agent.source] ?? false}
                disabled={disabled}
                state={sourceStates?.[agent.source]}
                expanded={expanded === agent.source}
                onExpand={() =>
                  setExpanded((current) =>
                    current === agent.source ? null : agent.source,
                  )
                }
                onToggle={onToggle}
                onSetup={onSetup}
                onToggleEntity={onToggleEntity}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

interface ResponderAgentCardProps {
  agent: ResponderAgentDefinition;
  armed: boolean;
  disabled?: boolean;
  state?: ResponderSourceState;
  expanded: boolean;
  onExpand: () => void;
  onToggle: (source: ResponderAgentSource, enabled: boolean) => void;
  onSetup?: (source: ResponderAgentSource) => void;
  onToggleEntity?: (source: ResponderAgentSource, entityId: string) => void;
}

const ResponderAgentCard = memo(function ResponderAgentCard({
  agent,
  armed: armedValue,
  disabled,
  state,
  expanded,
  onExpand,
  onToggle,
  onSetup,
  onToggleEntity,
}: ResponderAgentCardProps) {
  const meta = getSourceProductMeta(agent.sourceProduct);
  const requiresSetup = state?.requiresSetup ?? false;
  const loading = state?.loading ?? false;
  const accentColor = meta?.color ?? "var(--accent-9)";
  const Icon = meta?.Icon;
  const isInteractive = !disabled && !loading;
  const entities = state?.entities ?? [];
  const entitiesLoading = state?.entitiesLoading ?? false;
  // A source whose entities the user creates gets no master switch. Arming it would write to
  // every entity at once, and switching back would not restore the earlier subset. Such a
  // source is on when any of its entities is, since no config row records it.
  const hasMasterSwitch = !agent.entitiesAreUserCreated;
  const enabledCount = entities.filter((entity) => entity.enabled).length;
  const armed = hasMasterSwitch ? armedValue : enabledCount > 0;
  const statusBadge =
    STATUS_BADGE[resolveAgentStatus(armed, state?.syncStatus)];

  const handleCardClick = useCallback(() => {
    if (!isInteractive) return;
    if (requiresSetup) {
      onSetup?.(agent.source);
      return;
    }
    onExpand();
  }, [agent.source, isInteractive, onExpand, onSetup, requiresSetup]);

  return (
    <div
      className={cn(
        AGENT_CARD_BASE_CLASS,
        armed ? "border-accent-6 bg-accent-2" : "border-border",
        isInteractive
          ? armed
            ? AGENT_CARD_INTERACTIVE_ARMED_CLASS
            : AGENT_CARD_INTERACTIVE_IDLE_CLASS
          : "cursor-default",
      )}
    >
      <div className="flex items-start justify-between gap-3 p-3">
        {/* The label block is the expander, so the switch beside it stays its own control. */}
        <button
          type="button"
          onClick={handleCardClick}
          disabled={!isInteractive}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Collapse" : "Expand"} ${agent.label}`}
          className="flex min-w-0 flex-1 cursor-pointer items-start gap-3 text-left disabled:cursor-default"
        >
          <AgentIcon accentColor={accentColor} Icon={Icon} />
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <Text className="font-medium text-foreground text-xs">
                {agent.label}
              </Text>
              {agent.alpha ? (
                <InboxBadge variant="warning">Alpha</InboxBadge>
              ) : null}
            </div>
            <Text className="text-muted-foreground text-xs leading-snug">
              {agent.description}
            </Text>
            {agent.entityNoun && !entitiesLoading ? (
              <Text className="text-muted-foreground text-xs">
                {entities.length > 0
                  ? `${enabledCount} of ${entities.length} ${agent.entityNoun} on`
                  : `No ${agent.entityNoun} yet`}
              </Text>
            ) : null}
          </div>
        </button>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="flex items-center gap-1">
            <InboxBadge variant={statusBadge.variant}>
              {statusBadge.label}
            </InboxBadge>
            <CaretRightIcon
              size={12}
              aria-hidden
              className={cn(
                "text-muted-foreground transition-transform",
                expanded && "rotate-90",
              )}
            />
          </div>
          {loading ? (
            <Spinner size="md" />
          ) : requiresSetup ? (
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => onSetup?.(agent.source)}
            >
              Connect
            </Button>
          ) : hasMasterSwitch ? (
            <Switch
              checked={armed}
              onCheckedChange={(checked) => onToggle(agent.source, checked)}
              disabled={disabled}
              aria-label={`Arm ${agent.label}`}
            />
          ) : null}
        </div>
      </div>

      {expanded ? (
        <AgentExpansion
          agent={agent}
          entities={entities}
          entitiesLoading={entitiesLoading}
          pendingEntities={state?.pendingEntities}
          disabled={disabled}
          onToggleEntity={onToggleEntity}
        />
      ) : null}
    </div>
  );
});

function AgentExpansion({
  agent,
  entities,
  entitiesLoading,
  pendingEntities,
  disabled,
  onToggleEntity,
}: {
  agent: ResponderAgentDefinition;
  entities: ResponderEntity[];
  entitiesLoading: boolean;
  pendingEntities?: Record<string, boolean>;
  disabled?: boolean;
  onToggleEntity?: (source: ResponderAgentSource, entityId: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const noun = agent.entityNoun ?? "items";
  const visible = showAll ? entities : entities.slice(0, ENTITY_VISIBLE_LIMIT);
  const hiddenCount = entities.length - visible.length;
  const manageUrl = agent.manageUrl ? projectUrl(agent.manageUrl) : null;

  return (
    <div className="border-border border-t bg-muted">
      <div className="flex flex-col gap-2 px-3 py-2.5">
        {agent.detail ? (
          <Text className="text-muted-foreground text-xs leading-snug">
            {agent.detail}
          </Text>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          {agent.docsUrl ? (
            <ExternalLink href={agent.docsUrl}>
              Learn about {agent.docsLabel ?? agent.label}
            </ExternalLink>
          ) : null}
          {manageUrl ? (
            <ExternalLink href={manageUrl}>
              Manage {noun} in PostHog
            </ExternalLink>
          ) : null}
        </div>
      </div>

      {entitiesLoading ? (
        <div className="border-border border-t px-3 py-3">
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : entities.length > 0 ? (
        <>
          {visible.map((entity) => (
            <EntityRow
              key={entity.id}
              entity={entity}
              pending={pendingEntities?.[entity.id] ?? false}
              disabled={disabled}
              onToggle={() => onToggleEntity?.(agent.source, entity.id)}
            />
          ))}
          {hiddenCount > 0 || showAll ? (
            <div className="flex border-border border-t px-3 py-1.5">
              <Button
                type="button"
                variant="link-muted"
                size="xs"
                onClick={() => setShowAll(!showAll)}
              >
                {hiddenCount > 0
                  ? `Show ${hiddenCount} more ${noun}`
                  : "Show fewer"}
              </Button>
            </div>
          ) : null}
        </>
      ) : agent.entityNoun ? (
        <div className="border-border border-t px-3 py-2.5">
          <Text className="text-muted-foreground text-xs">
            No {noun} yet. Create one in PostHog to give this source something
            to watch.
          </Text>
        </div>
      ) : null}
    </div>
  );
}

function EntityRow({
  entity,
  pending,
  disabled,
  onToggle,
}: {
  entity: ResponderEntity;
  pending: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex items-center gap-2 border-border border-t px-3 py-2">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-w-0 items-center gap-2">
          <Text
            className={cn(
              "truncate text-xs",
              entity.enabled
                ? "font-medium text-foreground"
                : "text-muted-foreground",
            )}
          >
            {entity.name}
          </Text>
          {entity.kind ? (
            <InboxBadge variant="default" className="shrink-0 capitalize">
              {entity.kind}
            </InboxBadge>
          ) : null}
        </div>
        {entity.detail ? (
          <Text className="truncate text-muted-foreground text-xs">
            {entity.detail}
          </Text>
        ) : null}
      </div>
      {pending ? (
        <Spinner size="sm" />
      ) : (
        <Switch
          size="sm"
          checked={entity.enabled}
          onCheckedChange={onToggle}
          disabled={disabled}
          aria-label={entity.name}
        />
      )}
    </div>
  );
}

function ExternalLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => {
        e.preventDefault();
        void openUrlInBrowser(href);
      }}
      className="inline-flex items-center gap-1 text-accent-9 text-xs no-underline"
    >
      {children}
      <ArrowSquareOutIcon size={11} />
    </a>
  );
}

function AgentIcon({
  accentColor,
  Icon,
}: {
  accentColor: string;
  Icon?: ComponentType<IconProps>;
}) {
  return (
    <div
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md ring-1 ring-border ring-inset"
      style={{
        backgroundColor: `color-mix(in srgb, ${accentColor} 12%, transparent)`,
      }}
    >
      {Icon ? <Icon size={18} style={{ color: accentColor }} /> : null}
    </div>
  );
}

function ResponderAgentCardSkeleton() {
  return (
    <div className={cn(AGENT_CARD_BASE_CLASS, "border-border p-3")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <Skeleton className="h-3 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
            <Skeleton className="h-3 w-5/6" />
          </div>
        </div>
        <Skeleton className="h-5 w-18 shrink-0" />
      </div>
    </div>
  );
}

export function ResponderAgentRosterSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      {RESPONDER_AGENT_GROUPS.map((group) => (
        <div key={group.label} className="flex flex-col gap-2">
          <Skeleton className="h-3 w-25" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {group.agents.map((agent) => (
              <ResponderAgentCardSkeleton key={agent.source} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
