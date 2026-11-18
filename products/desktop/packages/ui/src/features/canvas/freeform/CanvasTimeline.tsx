import { PulseIcon, Sparkle } from "@phosphor-icons/react";
import type { CanvasVersion } from "@posthog/core/canvas/dashboardSchemas";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { formatRelativeAge } from "@posthog/shared";
import { useCanvasVersions } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";

function versionTitle(version: CanvasVersion): string {
  const prompt = version.prompt?.trim();
  if (prompt) return prompt;
  return version.parentVersionId ? "Published a change" : "Created the canvas";
}

function TimelineRow({
  version,
  label,
  live,
  viewing,
  last,
  onOpen,
}: {
  version: CanvasVersion;
  label: string | null;
  live: boolean;
  viewing: boolean;
  last: boolean;
  onOpen: () => void;
}) {
  const byAgent = !!version.taskId;
  return (
    <li className="relative flex gap-3 pl-1">
      {last ? null : (
        <span
          aria-hidden
          className="absolute top-5 bottom-0 left-[9px] w-px bg-border"
        />
      )}
      <span
        aria-hidden
        className={`relative mt-1.5 flex size-3 shrink-0 items-center justify-center rounded-full border ${live ? "border-primary bg-primary" : "border-border bg-background"}`}
      />
      <button
        type="button"
        onClick={onOpen}
        data-selected={viewing || undefined}
        className="mb-1 flex min-w-0 flex-1 flex-col gap-0.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-fill-hover data-selected:bg-fill-selected"
      >
        <span className="line-clamp-2 text-foreground text-xs">
          {versionTitle(version)}
        </span>
        <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
          {byAgent ? (
            <span className="flex items-center gap-1">
              <Sparkle size={11} />
              Agent
            </span>
          ) : (
            <span className="truncate">{version.createdBy ?? "Someone"}</span>
          )}
          <span aria-hidden>·</span>
          <span className="shrink-0">
            {formatRelativeAge(version.createdAt)}
          </span>
          {label ? (
            <>
              <span aria-hidden>·</span>
              <span className="shrink-0">{label}</span>
            </>
          ) : null}
          {live ? (
            <span className="ml-auto shrink-0 font-medium text-primary">
              Live
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

export function CanvasTimeline({
  dashboardId,
  liveVersionId,
  viewingVersionId,
  versionLabel,
  onOpen,
}: {
  dashboardId: string;
  liveVersionId: string | null;
  viewingVersionId: string | null;
  versionLabel: (versionId: string) => string | null;
  onOpen: (versionId: string | null) => void;
}) {
  const { versions, isLoading } = useCanvasVersions(dashboardId);
  if (isLoading) return <LoadingState />;
  if (versions.length === 0) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PulseIcon size={24} />
          </EmptyMedia>
          <EmptyTitle>No changes yet</EmptyTitle>
          <EmptyDescription>
            Every edit to this canvas, by you or an agent, shows here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  const ordered = versions.toSorted((a, b) => b.createdAt - a.createdAt);
  const viewing = viewingVersionId ?? liveVersionId;
  return (
    <div className="h-full overflow-y-auto px-3 py-3">
      <ol className="flex flex-col">
        {ordered.map((version, index) => (
          <TimelineRow
            key={version.id}
            version={version}
            label={versionLabel(version.id)}
            live={version.id === liveVersionId}
            viewing={version.id === viewing}
            last={index === ordered.length - 1}
            onOpen={() => onOpen(version.id)}
          />
        ))}
      </ol>
    </div>
  );
}
