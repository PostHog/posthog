import { CheckIcon, CopyIcon } from "@phosphor-icons/react";
import type { PostHogObjectArtifactMetadata } from "@posthog/core/canvas/runArtifactSchemas";
import {
  Badge,
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Heading,
  Skeleton,
  Text,
} from "@posthog/quill";
import { useEvidenceUrl } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
import {
  type EvidenceCardData,
  fetchEvidencePreview,
} from "@posthog/ui/features/editor/evidencePreview";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useCopy } from "@posthog/ui/primitives/useCopy";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import {
  getObjectKind,
  POSTHOG_OBJECT_ICON_COLOR,
} from "@posthog/ui/utils/objectKinds";
import { ExperimentResultsSummary } from "./ExperimentResultsSummary";
import { PostHogObjectDetails } from "./PostHogObjectDetails";

function StatStrip({
  stats,
}: {
  stats: Array<{ label: string; value: string }>;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.slice(0, 8).map((stat) => (
        <div
          key={stat.label}
          className="rounded-lg border border-border bg-card px-3.5 py-2.5"
        >
          <div className="truncate text-[11px] text-muted-foreground">
            {stat.label}
          </div>
          <div className="mt-0.5 truncate font-semibold text-foreground text-lg tabular-nums tracking-tight">
            {stat.value}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The object's identifier as a labeled chip; clicking copies it. A quill
 * Button in the same variant and size as "Open in PostHog" beside it, so the
 * two read as one control row.
 */
function IdChip({ id }: { id: string }) {
  const { copied, copy } = useCopy();
  return (
    <Button
      variant="outline"
      size="sm"
      data-attr="posthog-object-copy-reference"
      aria-label={copied ? "ID copied" : "Copy ID"}
      onClick={() => copy(id)}
      className="max-w-44"
    >
      <span className="font-medium text-[10px] text-muted-foreground uppercase tracking-wide">
        ID
      </span>
      <span className="truncate font-mono">{id}</span>
      {copied ? <CheckIcon size={12} /> : <CopyIcon size={12} />}
    </Button>
  );
}

const STATUS_BADGE_VARIANT = {
  positive: "success",
  neutral: "default",
  caution: "warning",
  critical: "destructive",
} as const;

function FactChips({ facts }: { facts: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {facts.map((fact) => (
        <span
          key={fact}
          className="rounded-md border border-border bg-muted px-2 py-0.5 text-muted-foreground text-xs"
        >
          {fact}
        </span>
      ))}
    </div>
  );
}

function ObjectContent({ preview }: { preview: EvidenceCardData }) {
  // A dashboard is its metrics: render each tile's insight as a live chart
  // and skip the descriptive cards, which only restate what the charts show.
  if (preview.tiles && preview.tiles.length > 0) {
    return (
      <div className="flex flex-col gap-3">
        {preview.tiles.map((tile, index) => (
          <MessageChartCard
            key={`${tile.shortId}:${index}`}
            spec={{ mode: "insight", shortId: tile.shortId }}
            blockKey={`artifact:dashboard-tile:${index}:${tile.shortId}`}
          />
        ))}
      </div>
    );
  }
  const stats = (preview.stats ?? []).filter((stat) => stat.value);
  return (
    <div className="flex flex-col gap-3">
      {stats.length > 0 ? (
        <StatStrip stats={stats} />
      ) : preview.facts && preview.facts.length > 0 ? (
        <FactChips facts={preview.facts} />
      ) : null}
      <PostHogObjectDetails preview={preview} />
    </div>
  );
}

function UnavailableObject({
  isError,
  objectKind,
}: {
  isError: boolean;
  objectKind: string;
}) {
  const ObjectIcon = getObjectKind(objectKind).icon;
  return (
    <Empty className="rounded-lg border border-border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ObjectIcon size={18} />
        </EmptyMedia>
        <EmptyTitle>
          {isError
            ? "Couldn't load this object"
            : "This object is not available in the current project"}
        </EmptyTitle>
        <EmptyDescription>
          {isError
            ? "Try again, or open PostHog to review it."
            : "Check the identifier or open PostHog to review access."}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

export interface PostHogObjectViewProps {
  objectKind: string;
  objectId: string;
  /** Shown while the preview loads or when the object has no live name. */
  fallbackName: string;
  url: string | null;
  /** Omitted when the page isn't backed by a run artifact (chip-opened). */
  occurrenceCount?: number;
  state: "loading" | "error" | "missing" | "ready";
  preview: EvidenceCardData | null;
}

/** Pure page body; `PostHogObjectPage` resolves the preview and URL. */
export function PostHogObjectPageView({
  objectKind,
  objectId,
  fallbackName,
  url,
  occurrenceCount,
  state,
  preview,
}: PostHogObjectViewProps) {
  const object = getObjectKind(objectKind);
  const ObjectIcon = object.icon;
  const usesChartRenderer = objectKind === "insight" || objectKind === "hogql";
  const title = preview?.title ?? fallbackName;
  const status = preview?.status;
  // The product name earns its place only when it adds context ("Insight ·
  // Product analytics"); drop it when it restates the kind ("Feature flag ·
  // Feature flags", "SQL query · SQL editor").
  const showSource = !object.source
    .toLowerCase()
    .split(" ")[0]
    .startsWith(object.kindLabel.toLowerCase().split(" ")[0]);
  const metaLine = [
    object.kindLabel,
    showSource ? object.source : null,
    preview?.detail,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col px-8 py-8">
        <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <div className="flex min-w-0 flex-1 basis-72 items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border bg-card">
              <ObjectIcon size={20} color={POSTHOG_OBJECT_ICON_COLOR} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Heading size="base" className="truncate tracking-tight">
                  {title}
                </Heading>
                {status && (
                  <Badge variant={STATUS_BADGE_VARIANT[status.tone]}>
                    {status.label}
                  </Badge>
                )}
              </div>
              <Text size="sm" variant="muted" className="mt-0.5 block truncate">
                {metaLine}
              </Text>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {/* A hogql reference's id is the SQL itself, not an identifier
                worth copying; the chart card already shows the query. */}
            {objectKind !== "hogql" && <IdChip id={objectId} />}
            {url && (
              <Button
                variant="outline"
                size="sm"
                data-attr="posthog-object-open-in-posthog"
                onClick={() => openExternalUrl(url)}
              >
                Open in PostHog ↗
              </Button>
            )}
          </div>
        </header>

        <div className="mt-6">
          {objectKind === "experiment" ? (
            <div className="flex flex-col gap-3">
              <ExperimentResultsSummary
                display="full"
                loadState={state}
                results={preview?.experimentResults}
              />
              {preview && <PostHogObjectDetails preview={preview} />}
            </div>
          ) : usesChartRenderer ? (
            <MessageChartCard
              spec={
                objectKind === "insight"
                  ? { mode: "insight", shortId: objectId }
                  : { mode: "hogql", query: objectId }
              }
              blockKey={`artifact:${objectKind}:${objectId}`}
            />
          ) : state === "loading" ? (
            // Mirrors the loaded layout (stat strip, chart, detail card) so
            // content lands in place instead of reflowing the page.
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[0, 1, 2, 3].map((tile) => (
                  <Skeleton key={tile} className="h-[62px] w-full rounded-lg" />
                ))}
              </div>
              <Skeleton className="h-56 w-full rounded-lg" />
              <Skeleton className="h-40 w-full rounded-lg" />
            </div>
          ) : preview ? (
            <ObjectContent preview={preview} />
          ) : (
            <UnavailableObject
              isError={state === "error"}
              objectKind={objectKind}
            />
          )}
        </div>

        {occurrenceCount !== undefined && (
          <div className="mt-6 border-border border-t pt-4 text-muted-foreground text-xs">
            Referenced {occurrenceCount.toLocaleString()}{" "}
            {occurrenceCount === 1 ? "time" : "times"} in this task
          </div>
        )}
      </div>
    </div>
  );
}

export function PostHogObjectPage({
  metadata,
  fallbackName,
}: {
  /** Only kind + id when opened from an inline reference chip. */
  metadata: Pick<PostHogObjectArtifactMetadata, "object_kind" | "object_id"> &
    Partial<Omit<PostHogObjectArtifactMetadata, "object_kind" | "object_id">>;
  fallbackName: string;
}) {
  const usesChartRenderer =
    metadata.object_kind === "insight" || metadata.object_kind === "hogql";
  const query = useAuthenticatedQuery(
    ["evidence-preview", metadata.object_kind, metadata.object_id],
    (client) =>
      fetchEvidencePreview(client, {
        kind: metadata.object_kind,
        id: metadata.object_id,
      }),
    {
      enabled: !usesChartRenderer,
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  );
  const url = useEvidenceUrl(
    metadata.object_kind,
    query.data?.resolvedId ?? metadata.object_id,
  );
  const state = usesChartRenderer
    ? "ready"
    : query.isPending
      ? "loading"
      : query.isError
        ? "error"
        : query.data
          ? "ready"
          : "missing";

  return (
    <PostHogObjectPageView
      objectKind={metadata.object_kind}
      objectId={metadata.object_id}
      fallbackName={fallbackName}
      url={url}
      occurrenceCount={metadata.occurrence_count}
      state={state}
      preview={query.data ?? null}
    />
  );
}
