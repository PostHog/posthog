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
import { getObjectKind } from "@posthog/ui/utils/objectKinds";

function ObjectContent({
  metadata,
  preview,
}: {
  metadata: PostHogObjectArtifactMetadata;
  preview: EvidenceCardData | null;
}) {
  if (metadata.object_kind === "insight") {
    return (
      <MessageChartCard
        spec={{ mode: "insight", shortId: metadata.object_id }}
        blockKey={`artifact:${metadata.object_kind}:${metadata.object_id}`}
      />
    );
  }
  if (metadata.object_kind === "hogql") {
    return (
      <MessageChartCard
        spec={{ mode: "hogql", query: metadata.object_id }}
        blockKey={`artifact:${metadata.object_kind}:${metadata.object_id}`}
      />
    );
  }
  if (metadata.object_kind === "replay") {
    return (
      <MessageChartCard
        spec={{ mode: "replay", sessionId: metadata.object_id }}
        blockKey={`artifact:${metadata.object_kind}:${metadata.object_id}`}
      />
    );
  }
  if (!preview) {
    return (
      <div className="rounded-md border border-border bg-muted p-4">
        <Text>This object is not available in the current project.</Text>
        <Text className="mt-1 text-muted-foreground text-sm">
          Check the identifier or open PostHog to review access.
        </Text>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-border bg-card p-4">
      {preview.detail && (
        <Text className="text-muted-foreground">{preview.detail}</Text>
      )}
      {preview.facts && preview.facts.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {preview.facts.map((fact) => (
            <span
              key={fact}
              className="rounded-sm bg-muted px-2 py-1 text-muted-foreground text-xs"
            >
              {fact}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function PostHogObjectPage({
  metadata,
  fallbackName,
}: {
  metadata: PostHogObjectArtifactMetadata;
  fallbackName: string;
}) {
  const object = getObjectKind(metadata.object_kind);
  const ObjectIcon = object.icon;
  const { copied, copy } = useCopy();
  const usesBlockRenderer =
    metadata.object_kind === "insight" ||
    metadata.object_kind === "hogql" ||
    metadata.object_kind === "replay";
  const query = useAuthenticatedQuery(
    ["evidence-preview", metadata.object_kind, metadata.object_id],
    (client) =>
      fetchEvidencePreview(client, {
        kind: metadata.object_kind,
        id: metadata.object_id,
      }),
    {
      enabled: !usesBlockRenderer,
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

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-6 py-7">
        <header className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-1.5 text-muted-foreground text-xs uppercase tracking-wide">
              <ObjectIcon size={14} />
              <span>{object.kindLabel}</span>
              <span>·</span>
              <span>{object.source}</span>
            </div>
            <Heading size="xl" className="truncate">
              {title}
            </Heading>
            <div className="mt-2 flex items-center gap-1 font-mono text-muted-foreground text-xs">
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
          </div>
          {url && (
            <Button
              variant="outline"
              data-attr="posthog-object-open-in-posthog"
              onClick={() => openExternalUrl(url)}
            >
              Open in PostHog ↗
            </Button>
          )}
        </header>

        {usesBlockRenderer ? (
          <ObjectContent metadata={metadata} preview={null} />
        ) : query.isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-44 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : query.isError ? (
          <ObjectContent metadata={metadata} preview={null} />
        ) : (
          <ObjectContent metadata={metadata} preview={query.data ?? null} />
        )}

        <div className="border-border border-t pt-4 text-muted-foreground text-xs">
          Referenced {metadata.occurrence_count.toLocaleString()}{" "}
          {metadata.occurrence_count === 1 ? "time" : "times"} in this task
        </div>
      </div>
    </div>
  );
}
