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
import type {
  ExternalDataSource,
  SignalSourceConfig,
} from "@posthog/api-client/posthog-client";
import { formatRepoPreview } from "@posthog/core/settings/githubRepoSummary";
import { Button, Spinner, Switch } from "@posthog/quill";
import {
  EXTERNAL_INBOX_SOURCES,
  type ToggleableSourceProduct,
} from "@posthog/shared";
import { GitHubSourceRepositoriesDialog } from "@posthog/ui/features/inbox/components/GitHubSourceRepositoriesDialog";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { Badge } from "@posthog/ui/primitives/Badge";
import { memo, useCallback, useState } from "react";

export type SignalSourceValues = Record<ToggleableSourceProduct, boolean>;

const SORTED_EXTERNAL_INBOX_SOURCES = [...EXTERNAL_INBOX_SOURCES].sort((a, b) =>
  a.label.localeCompare(b.label),
);

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
  compact?: boolean;
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
  compact,
}: SignalSourceToggleCardProps) {
  const statusInfo = checked ? syncStatusLabel(syncStatus) : null;
  const control = (() => {
    if (loading) {
      return <Spinner />;
    }

    if (requiresSetup) {
      return (
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={onSetup}
          disabled={disabled}
        >
          Enable
        </Button>
      );
    }

    return (
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      />
    );
  })();

  return (
    <div
      className={`rounded-(--radius-3) border bg-(--color-panel-solid) transition duration-150 ${compact ? "p-2" : "p-3"} ${checked ? "border-(--accent-6)" : "border-border"}`}
    >
      {compact ? (
        <div className="flex items-center gap-3">
          <div className="shrink-0 text-gray-11">{icon}</div>
          <div className="w-56 min-w-0 max-w-[60%]">
            <div className="flex min-w-0 items-center gap-2">
              <span
                title={label}
                className="min-w-0 flex-1 truncate font-medium text-gray-12 text-sm"
              >
                {label}
              </span>
              {labelSuffix}
            </div>
            {statusInfo && (
              <span
                style={{ color: statusInfo.color }}
                className="mt-0.5 block text-[13px] leading-none"
              >
                {statusInfo.text}
              </span>
            )}
          </div>
          <span
            title={description}
            className="min-w-0 flex-1 truncate text-[13px] text-gray-11"
          >
            {description}
          </span>
          <div className="flex w-16 shrink-0 justify-end">{control}</div>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="shrink-0 text-gray-11">{icon}</div>
            <div className="flex flex-col gap-1">
              <div className="flex min-w-0 items-center gap-2">
                <span className="font-medium text-gray-12 text-sm">
                  {label}
                </span>
                {labelSuffix}
                {statusInfo && (
                  <span
                    style={{ color: statusInfo.color }}
                    className="text-[13px]"
                  >
                    {statusInfo.text}
                  </span>
                )}
              </div>
              <span className="text-[13px] text-gray-11">{description}</span>
              {docsUrl && (
                <span className="text-[13px] text-gray-11">
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
                </span>
              )}
            </div>
          </div>
          {control}
        </div>
      )}
      {statusSection && <div className="ml-[32px]">{statusSection}</div>}
    </div>
  );
});

interface SourceState {
  requiresSetup: boolean;
  loading: boolean;
  syncStatus?: SignalSourceConfig["status"];
  externalSource?: ExternalDataSource;
  /** GitHub only: the repositories the warehouse source syncs. */
  configuredRepos?: string[];
}

/**
 * The GitHub source syncs a fixed repository list, unlike credential-based sources that pull
 * everything, so the card says which repositories and offers to change them.
 */
function GithubSourceRepositories({
  source,
  repos,
}: {
  source: ExternalDataSource;
  repos: string[];
}) {
  const [editing, setEditing] = useState(false);
  const label =
    repos.length === 0
      ? "No repositories selected"
      : `${repos.length} ${repos.length === 1 ? "repository" : "repositories"}: ${formatRepoPreview(repos)}`;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2">
      <span
        title={repos.join(", ")}
        className="min-w-0 truncate text-[12px] text-gray-11"
      >
        {label}
      </span>
      <Button
        type="button"
        variant="outline"
        size="xs"
        onClick={() => setEditing(true)}
      >
        Edit repositories
      </Button>
      {editing ? (
        <GitHubSourceRepositoriesDialog
          source={source}
          open={editing}
          onClose={() => setEditing(false)}
        />
      ) : null}
    </div>
  );
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
  const githubSource =
    product === "github" && state?.externalSource && state.configuredRepos
      ? { source: state.externalSource, repos: state.configuredRepos }
      : null;

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
      statusSection={
        githubSource ? (
          <GithubSourceRepositories
            source={githubSource.source}
            repos={githubSource.repos}
          />
        ) : undefined
      }
      compact
    />
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
    <div className="mt-2 flex items-center gap-2">
      <CircleNotchIcon size={14} className="animate-spin text-(--accent-11)" />
      <span className="text-(--accent-11) text-[13px]">{message}</span>
    </div>
  );
}

interface SignalSourceTogglesProps {
  value: SignalSourceValues;
  onToggle: (source: ToggleableSourceProduct, enabled: boolean) => void;
  disabled?: boolean;
  sourceStates?: Partial<Record<ToggleableSourceProduct, SourceState>>;
  onSetup?: (source: ToggleableSourceProduct) => void;
}

export function SignalSourceToggles({
  value,
  onToggle,
  disabled,
  sourceStates,
  onSetup,
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
  const toggleLlmAnalytics = useCallback(
    (checked: boolean) => onToggle("llm_analytics", checked),
    [onToggle],
  );

  return (
    <div className="flex flex-col gap-5">
      {/* PostHog data */}
      <section className="flex min-w-0 flex-col gap-2">
        <span className="font-medium text-(--gray-9) text-[13px]">
          PostHog data
        </span>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
          <SignalSourceToggleCard
            icon={<BrainIcon size={20} />}
            label="AI observability"
            description="Quality problems in your AI features. Set up evaluations to start getting signals."
            checked={value.llm_analytics}
            onCheckedChange={toggleLlmAnalytics}
            disabled={disabled}
            docsUrl="https://posthog.com/docs/ai-evals"
            docsLabel="evaluations"
          />
        </div>
      </section>

      {/* External sources — data-driven from the shared source registry */}
      <section className="flex min-w-0 flex-col gap-2">
        <span className="font-medium text-(--gray-9) text-[13px]">
          External sources
        </span>
        <div className="flex flex-col gap-3">
          {SORTED_EXTERNAL_INBOX_SOURCES.map((source) => {
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
        </div>
      </section>
    </div>
  );
}

function SignalSourceToggleCardSkeleton({ compact }: { compact?: boolean }) {
  if (compact) {
    return (
      <div className="rounded-(--radius-3) border border-border bg-(--color-panel-solid) p-2">
        <div className="flex items-center gap-3">
          <div className="size-[20px] shrink-0 animate-pulse rounded bg-gray-4" />
          <div className="h-[12px] w-56 max-w-[60%] animate-pulse rounded bg-gray-4" />
          <div className="h-[11px] min-w-0 flex-1 animate-pulse rounded bg-gray-3" />
          <div className="h-[18px] w-16 shrink-0 animate-pulse rounded-full bg-gray-3" />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-(--radius-3) border border-border bg-(--color-panel-solid) p-3">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <div className="size-[20px] shrink-0 animate-pulse rounded bg-gray-4" />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="h-[12px] w-[50%] animate-pulse rounded bg-gray-4" />
            <div className="h-[11px] w-[80%] animate-pulse rounded bg-gray-3" />
          </div>
        </div>
        <div className="h-[18px] w-[32px] shrink-0 animate-pulse rounded-full bg-gray-3" />
      </div>
    </div>
  );
}

export function SignalSourceTogglesSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <section className="flex min-w-0 flex-col gap-2">
        <span className="font-medium text-(--gray-9) text-[13px]">
          PostHog data
        </span>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static loading placeholders
            <SignalSourceToggleCardSkeleton key={index} />
          ))}
        </div>
      </section>
      <section className="flex min-w-0 flex-col gap-2">
        <span className="font-medium text-(--gray-9) text-[13px]">
          External sources
        </span>
        <div className="flex flex-col gap-3">
          {Array.from({ length: SORTED_EXTERNAL_INBOX_SOURCES.length }).map(
            (_, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static loading placeholders
              <SignalSourceToggleCardSkeleton key={index} compact />
            ),
          )}
        </div>
      </section>
    </div>
  );
}
