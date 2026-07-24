import {
  ArrowSquareOutIcon,
  BrainIcon,
  BugIcon,
  ChatsIcon,
  CircleNotchIcon,
  FirstAidIcon,
  PlugIcon,
  VideoIcon,
} from "@phosphor-icons/react";
import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import { Button } from "@posthog/quill";
import {
  EXTERNAL_INBOX_SOURCES,
  type ToggleableSourceProduct,
} from "@posthog/shared";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Box, Flex, Spinner, Switch, Text, Tooltip } from "@radix-ui/themes";
import { memo, useCallback } from "react";

export type SignalSourceValues = Record<ToggleableSourceProduct, boolean>;

interface SignalSourceToggleCardProps {
  icon: React.ReactNode;
  label: string;
  labelSuffix?: React.ReactNode;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  requiresSetup?: boolean;
  onSetup?: () => void;
  loading?: boolean;
  statusSection?: React.ReactNode;
  syncStatus?: string | null;
  docsUrl?: string;
  docsLabel?: string;
}

function syncStatusLabel(status: string | null | undefined): {
  text: string;
  color: string;
} | null {
  if (!status) return null;
  switch (status) {
    case "running":
      return { text: "Syncing…", color: "var(--amber-11)" };
    case "completed":
      return { text: "Synced", color: "var(--green-11)" };
    case "failed":
      return { text: "Sync failed", color: "var(--red-11)" };
    default:
      return null;
  }
}

const SignalSourceToggleCard = memo(function SignalSourceToggleCard({
  icon,
  label,
  labelSuffix,
  description,
  checked,
  onCheckedChange,
  disabled,
  requiresSetup,
  onSetup,
  loading,
  statusSection,
  syncStatus,
  docsUrl,
  docsLabel,
}: SignalSourceToggleCardProps) {
  const statusInfo = checked ? syncStatusLabel(syncStatus) : null;

  return (
    <Box
      p="3"
      onClick={
        disabled || loading
          ? undefined
          : requiresSetup
            ? onSetup
            : () => onCheckedChange(!checked)
      }
      className={[
        "rounded-(--radius-3) border bg-(--color-panel-solid) transition duration-150",
        checked ? "border-(--accent-6)" : "border-border",
        disabled || loading
          ? "cursor-default"
          : "cursor-pointer hover:border-(--gray-6) hover:bg-(--gray-2) hover:shadow-sm",
      ].join(" ")}
    >
      <Flex align="center" justify="between" gap="4">
        <Flex align="center" gap="3">
          <Box className="shrink-0 text-gray-11">{icon}</Box>
          <Flex direction="column" gap="1">
            <Flex align="center" gap="2">
              <Text className="font-medium text-gray-12 text-sm">{label}</Text>
              {labelSuffix}
              {statusInfo && (
                <Text
                  style={{ color: statusInfo.color }}
                  className="text-[13px]"
                >
                  {statusInfo.text}
                </Text>
              )}
            </Flex>
            <Text className="text-[13px] text-gray-11">{description}</Text>
            {docsUrl && (
              <Text className="text-[13px] text-gray-11">
                <a
                  href={docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    window.open(docsUrl, "_blank", "noopener");
                  }}
                  className="inline-flex items-center gap-[4px] text-(--accent-11) no-underline"
                >
                  Learn about {docsLabel ?? label}
                  <ArrowSquareOutIcon size={11} />
                </a>
              </Text>
            )}
          </Flex>
        </Flex>
        {loading ? (
          <Spinner size="2" />
        ) : requiresSetup ? (
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onSetup?.();
            }}
          >
            Enable
          </Button>
        ) : (
          <Switch
            checked={checked}
            onCheckedChange={onCheckedChange}
            disabled={disabled}
            onClick={(e) => e.stopPropagation()}
          />
        )}
      </Flex>
      {statusSection && <Box className="ml-[32px]">{statusSection}</Box>}
    </Box>
  );
});

interface SourceState {
  requiresSetup: boolean;
  loading: boolean;
  syncStatus?: SignalSourceConfig["status"];
}

/**
 * A single warehouse-source card. Its own component so the toggle/setup callbacks can be
 * memoized per product without breaking the rules of hooks (the grid renders one per source
 * from EXTERNAL_INBOX_SOURCES).
 */
const ExternalSourceCard = memo(function ExternalSourceCard({
  product,
  label,
  description,
  checked,
  state,
  disabled,
  onToggle,
  onSetup,
}: {
  product: ToggleableSourceProduct;
  label: string;
  description: string;
  checked: boolean;
  state?: SourceState;
  disabled?: boolean;
  onToggle: (source: ToggleableSourceProduct, enabled: boolean) => void;
  onSetup?: (source: ToggleableSourceProduct) => void;
}) {
  const handleToggle = useCallback(
    (value: boolean) => onToggle(product, value),
    [onToggle, product],
  );
  const handleSetup = useCallback(() => onSetup?.(product), [onSetup, product]);
  const meta = getSourceProductMeta(product);
  const Icon = meta?.Icon ?? PlugIcon;

  return (
    <SignalSourceToggleCard
      icon={<Icon size={20} style={meta ? { color: meta.color } : undefined} />}
      label={label}
      description={description}
      checked={checked}
      onCheckedChange={handleToggle}
      disabled={disabled}
      requiresSetup={state?.requiresSetup}
      onSetup={handleSetup}
      loading={state?.loading}
      syncStatus={state?.syncStatus}
    />
  );
});

interface EvaluationsSectionProps {
  evaluationsUrl: string;
}

export const EvaluationsSection = memo(function EvaluationsSection({
  evaluationsUrl,
}: EvaluationsSectionProps) {
  return (
    <Box
      p="3"
      onClick={() => window.open(evaluationsUrl, "_blank", "noopener")}
      className="cursor-pointer rounded-(--radius-3) border border-border bg-(--color-panel-solid) transition duration-150 hover:border-(--gray-6) hover:bg-(--gray-2) hover:shadow-sm"
    >
      <Flex align="center" justify="between" gap="4">
        <Flex align="center" gap="3">
          <Box className="shrink-0 text-gray-11">
            <BrainIcon size={20} />
          </Box>
          <Flex direction="column" gap="1">
            <Flex align="center" gap="2">
              <Text className="font-medium text-gray-12 text-sm">
                AI observability
              </Text>
              <Tooltip content="This is only visible to staff users of PostHog">
                <Badge color="blue">Internal</Badge>
              </Tooltip>
            </Flex>
            <Text className="text-[13px] text-gray-11">
              Monitor how your AI features are performing
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
                className="inline-flex items-center gap-[4px] text-(--accent-11) no-underline"
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

function SourceRunningIndicator({
  status,
  message,
}: {
  status: SignalSourceConfig["status"];
  message: string;
}) {
  if (status !== "running") {
    return null;
  }
  return (
    <Flex align="center" gap="2" mt="2">
      <CircleNotchIcon size={14} className="animate-spin text-(--accent-11)" />
      <Text className="text-(--accent-11) text-[13px]">{message}</Text>
    </Flex>
  );
}

interface SignalSourceTogglesProps {
  value: SignalSourceValues;
  onToggle: (source: ToggleableSourceProduct, enabled: boolean) => void;
  disabled?: boolean;
  sourceStates?: Partial<Record<ToggleableSourceProduct, SourceState>>;
  onSetup?: (source: ToggleableSourceProduct) => void;
  evaluationsUrl?: string;
}

export function SignalSourceToggles({
  value,
  onToggle,
  disabled,
  sourceStates,
  onSetup,
  evaluationsUrl,
}: SignalSourceTogglesProps) {
  const toggleSessionReplay = useCallback(
    (checked: boolean) => onToggle("session_replay", checked),
    [onToggle],
  );
  const toggleErrorTracking = useCallback(
    (checked: boolean) => onToggle("error_tracking", checked),
    [onToggle],
  );
  const toggleConversations = useCallback(
    (checked: boolean) => onToggle("conversations", checked),
    [onToggle],
  );
  const toggleHealthChecks = useCallback(
    (checked: boolean) => onToggle("health_checks", checked),
    [onToggle],
  );

  return (
    <Flex gap="4">
      {/* PostHog data */}
      <Flex direction="column" gap="2" className="min-w-0 flex-1">
        <Text className="font-medium text-(--gray-9) text-[13px]">
          PostHog data
        </Text>
        <Flex direction="column" gap="3">
          <SignalSourceToggleCard
            icon={<BugIcon size={20} />}
            label="Error Tracking"
            description="Surface new issues, reopenings and volume spikes"
            checked={value.error_tracking}
            onCheckedChange={toggleErrorTracking}
            disabled={disabled}
            syncStatus={sourceStates?.error_tracking?.syncStatus}
            docsUrl="https://posthog.com/docs/error-tracking"
            docsLabel="Error Tracking"
          />
          <SignalSourceToggleCard
            icon={<FirstAidIcon size={20} />}
            label="Health checks"
            description="Surface instrumentation problems — missing events, proxy gaps, outdated SDKs"
            checked={value.health_checks}
            onCheckedChange={toggleHealthChecks}
            disabled={disabled}
            syncStatus={sourceStates?.health_checks?.syncStatus}
            docsUrl="https://posthog.com/docs/sdk-health"
            docsLabel="Health checks"
          />
          <SignalSourceToggleCard
            icon={<ChatsIcon size={20} />}
            label="Support"
            description="Turn support conversations into Self-driving inputs"
            checked={value.conversations}
            onCheckedChange={toggleConversations}
            disabled={disabled}
            docsUrl="https://posthog.com/docs/support"
            docsLabel="Support"
          />
          <SignalSourceToggleCard
            icon={<VideoIcon size={20} />}
            label="Session Replay"
            labelSuffix={<Badge color="orange">Alpha</Badge>}
            description="Analyze recordings for UX issues"
            checked={value.session_replay}
            onCheckedChange={toggleSessionReplay}
            disabled={disabled}
            docsUrl="https://posthog.com/docs/session-replay"
            docsLabel="Session Replay"
            statusSection={
              value.session_replay ? (
                <SourceRunningIndicator
                  status={sourceStates?.session_replay?.syncStatus ?? null}
                  message="Session analysis run in progress now..."
                />
              ) : undefined
            }
          />
          {evaluationsUrl && (
            <EvaluationsSection evaluationsUrl={evaluationsUrl} />
          )}
        </Flex>
      </Flex>

      {/* External connections — data-driven from the shared source registry */}
      <Flex direction="column" gap="2" className="min-w-0 flex-1">
        <Text className="font-medium text-(--gray-9) text-[13px]">
          External connections
        </Text>
        <Flex direction="column" gap="3">
          {EXTERNAL_INBOX_SOURCES.map((source) => {
            const product = source.product;
            return (
              <ExternalSourceCard
                key={source.product}
                product={product}
                label={source.label}
                description={source.description}
                checked={value[product]}
                state={sourceStates?.[product]}
                disabled={disabled}
                onToggle={onToggle}
                onSetup={onSetup}
              />
            );
          })}
        </Flex>
      </Flex>
    </Flex>
  );
}

function SignalSourceToggleCardSkeleton() {
  return (
    <Box
      p="3"
      className="rounded-(--radius-3) border border-border bg-(--color-panel-solid)"
    >
      <Flex align="center" justify="between" gap="4">
        <Flex align="center" gap="3" className="min-w-0 flex-1">
          <Box className="size-[20px] shrink-0 animate-pulse rounded bg-gray-4" />
          <Flex direction="column" gap="2" className="min-w-0 flex-1">
            <Box className="h-[12px] w-[50%] animate-pulse rounded bg-gray-4" />
            <Box className="h-[11px] w-[80%] animate-pulse rounded bg-gray-3" />
          </Flex>
        </Flex>
        <Box className="h-[18px] w-[32px] shrink-0 animate-pulse rounded-full bg-gray-3" />
      </Flex>
    </Box>
  );
}

export function SignalSourceTogglesSkeleton() {
  return (
    <Flex gap="4">
      <Flex direction="column" gap="2" className="min-w-0 flex-1">
        <Text className="font-medium text-(--gray-9) text-[13px]">
          PostHog data
        </Text>
        <Flex direction="column" gap="3">
          {Array.from({ length: 4 }).map((_, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static loading placeholders
            <SignalSourceToggleCardSkeleton key={index} />
          ))}
        </Flex>
      </Flex>
      <Flex direction="column" gap="2" className="min-w-0 flex-1">
        <Text className="font-medium text-(--gray-9) text-[13px]">
          External connections
        </Text>
        <Flex direction="column" gap="3">
          {Array.from({ length: 4 }).map((_, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static loading placeholders
            <SignalSourceToggleCardSkeleton key={index} />
          ))}
        </Flex>
      </Flex>
    </Flex>
  );
}
