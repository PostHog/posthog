import { CheckIcon, CopyIcon } from "@phosphor-icons/react";
import type { PostHogObjectArtifactMetadata } from "@posthog/core/canvas/runArtifactSchemas";
import { Button, Heading, Skeleton, Text } from "@posthog/quill";
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
import { PostHogObjectDetails } from "./PostHogObjectDetails";

/** Headline numbers as a row of tiles; the page's first stop after the title. */
function StatStrip({
  stats,
}: {
  stats: Array<{ label: string; value: string }>;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {stats.slice(0, 8).map((stat) => (
        <div
          key={stat.label}
          className="rounded-lg border border-border bg-card px-4 py-3"
        >
          <div className="truncate text-muted-foreground text-xs">
            {stat.label}
          </div>
          <div className="mt-1 truncate font-semibold text-foreground text-xl tabular-nums tracking-tight">
            {stat.value}
          </div>
        </div>
      ))}
    </div>
  );
}

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
      <div className="flex flex-col gap-4">
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
    <div className="flex flex-col gap-4">
      {stats.length > 0 ? (
        <StatStrip stats={stats} />
      ) : preview.facts && preview.facts.length > 0 ? (
        <FactChips facts={preview.facts} />
      ) : null}
      <PostHogObjectDetails preview={preview} />
    </div>
  );
}

function UnavailableObject({ isError }: { isError: boolean }) {
  return (
    <div className="rounded-md border border-border bg-muted p-4">
      <Text>
        {isError
          ? "Couldn't load this object."
          : "This object is not available in the current project."}
      </Text>
      <Text className="mt-1 text-muted-foreground text-sm">
        {isError
          ? "Try again, or open PostHog to review it."
          : "Check the identifier or open PostHog to review access."}
      </Text>
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
  const object = getObjectKind(metadata.object_kind);
  const ObjectIcon = object.icon;
  const { copied, copy } = useCopy();
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
  // A flag cited by key or an event cited by name has no page under the cited
  // id; link out via the id the preview resolved, as EvidenceRefChip does.
  const url = useEvidenceUrl(
    metadata.object_kind,
    query.data?.resolvedId ?? metadata.object_id,
  );
  const title = query.data?.title ?? fallbackName;
  const url = useEvidenceUrl(
    metadata.object_kind,
    query.data?.resolvedId ?? metadata.object_id,
  );
  // The product name adds nothing when it just restates the kind ("Feature
  // flag · Feature flags"); keep it when it adds context ("Insight · Product
  // analytics").
  const showSource = !object.source
    .toLowerCase()
    .startsWith(object.kindLabel.toLowerCase());

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col px-8 py-8">
        <header>
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-1.5 text-muted-foreground text-xs uppercase tracking-wide">
              <ObjectIcon size={14} color={POSTHOG_OBJECT_ICON_COLOR} />
              <span>{object.kindLabel}</span>
              {showSource && (
                <>
                  <span>·</span>
                  <span>{object.source}</span>
                </>
              )}
            </div>
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
          <Heading size="xl" className="mt-2 truncate">
            {title}
          </Heading>
          {query.data?.detail && (
            <Text
              size="sm"
              variant="muted"
              className="mt-1.5 block leading-relaxed"
            >
              {query.data.detail}
            </Text>
          )}
          <div className="mt-2.5 flex items-center gap-1 font-mono text-muted-foreground text-xs">
            <span className="max-w-xl truncate">{metadata.object_id}</span>
            <button
              type="button"
              data-attr="posthog-object-copy-reference"
              aria-label={copied ? "Reference copied" : "Copy reference"}
              onClick={() => copy(metadata.object_id)}
              className="inline-flex size-6 cursor-pointer items-center justify-center rounded-sm border-0 bg-transparent hover:bg-fill-hover hover:text-foreground"
            >
              {copied ? <CheckIcon size={12} /> : <CopyIcon size={12} />}
            </button>
          </div>
        </header>

        <div className="mt-6">
          {usesChartRenderer ? (
            <MessageChartCard
              spec={
                metadata.object_kind === "insight"
                  ? { mode: "insight", shortId: metadata.object_id }
                  : { mode: "hogql", query: metadata.object_id }
              }
              blockKey={`artifact:${metadata.object_kind}:${metadata.object_id}`}
            />
          ) : query.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-44 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : query.data ? (
            <ObjectContent preview={query.data} />
          ) : (
            <UnavailableObject isError={query.isError} />
          )}
        </div>

        {metadata.occurrence_count !== undefined && (
          <div className="mt-6 border-border border-t pt-4 text-muted-foreground text-xs">
            Referenced {metadata.occurrence_count.toLocaleString()}{" "}
            {metadata.occurrence_count === 1 ? "time" : "times"} in this task
          </div>
        )}
      </div>
    </div>
  );
}
