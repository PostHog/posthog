import { CaretDown, DownloadSimple, Package, X } from "@phosphor-icons/react";
import {
  groupRunArtifactVersions,
  type RunArtifactVersions,
  runArtifactVersionKey,
} from "@posthog/core/canvas/runArtifactSchemas";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import { formatRelativeTimeLong, type TaskRunArtifact } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import { useArtifactDownload } from "@posthog/ui/features/sessions/useArtifactDownload";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { toast } from "@posthog/ui/primitives/toast";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useCompletedArtifactUploads } from "./countArtifactUploads";

type ArtifactGroup = RunArtifactVersions<TaskRunArtifact>;

interface CurrentUser {
  id?: number;
  first_name?: string | null;
}

// Labels mirror the artifact pane (TaskArtifactsList) so the same file reads
// the same way on both surfaces.
function uploaderLabel(
  artifact: TaskRunArtifact,
  currentUser: CurrentUser | undefined,
): string {
  if (artifact.uploaded_by !== "user") return "Agent";
  if (
    currentUser?.id !== undefined &&
    artifact.uploaded_by_user_id === currentUser.id
  ) {
    return currentUser.first_name?.trim() || "You";
  }
  return "Teammate";
}

/** Compact one-based version label: v1 is oldest, v{total} is newest. */
function versionShortLabel(index: number, total: number): string {
  return `v${total - index}`;
}

function versionMenuLabel(
  artifact: TaskRunArtifact,
  index: number,
  total: number,
  currentUser: CurrentUser | undefined,
): string {
  return [
    versionShortLabel(index, total),
    uploaderLabel(artifact, currentUser),
    artifact.uploaded_at ? formatRelativeTimeLong(artifact.uploaded_at) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function CloudArtifactDownloads({
  taskId,
  task,
}: {
  taskId: string | undefined;
  task: Task | undefined;
}) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const sessionArtifacts = useSessionSelector(
    taskId,
    (session) => session?.cloudArtifacts,
  );
  const cloudStatus = useSessionSelector(
    taskId,
    (session) => session?.cloudStatus,
  );
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const { download, downloadingId } = useArtifactDownload();
  const { data: currentUser } = useMeQuery();
  const [selectedVersionByName, setSelectedVersionByName] = useState<
    Record<string, string>
  >({});
  const [dismissalOverrides, setDismissalOverrides] = useState<
    Record<string, string | null>
  >({});
  const [showDismissed, setShowDismissed] = useState(false);
  const runId = task?.latest_run?.id;
  const runStatus = cloudStatus ?? task?.latest_run?.status;
  const isLive = runStatus === "queued" || runStatus === "in_progress";
  const events = useSessionSelector(taskId, (session) => session?.events);
  const completedUploads = useCompletedArtifactUploads(events ?? []);
  const { data: fetchedArtifacts, refetch } = useQuery({
    queryKey: [
      "cloudRunArtifacts",
      authIdentity,
      taskId,
      runId,
      completedUploads,
    ],
    queryFn: () =>
      sessionService.getCloudRunArtifacts(taskId ?? "", runId ?? ""),
    enabled:
      authIdentity !== null && taskId !== undefined && runId !== undefined,
    retry: false,
    staleTime: 15_000,
    // Tool completion triggers an immediate refresh; this only covers missing tool events.
    refetchInterval: isLive ? 120_000 : false,
  });

  const artifactManifest =
    fetchedArtifacts ?? sessionArtifacts ?? task?.latest_run?.artifacts;
  const groups = useMemo(
    () =>
      groupRunArtifactVersions(
        (artifactManifest ?? []).flatMap((artifact) => {
          if (artifact.type !== "output") return [];
          return [
            artifact.id && artifact.id in dismissalOverrides
              ? { ...artifact, dismissed_at: dismissalOverrides[artifact.id] }
              : artifact,
          ];
        }),
      ),
    [artifactManifest, dismissalOverrides],
  );
  const visibleGroups = groups.filter((group) => !group.dismissed);
  const dismissedGroups = groups.filter((group) => group.dismissed);

  const dismissal = useMutation({
    mutationFn: ({
      group,
      dismissed,
    }: {
      group: ArtifactGroup;
      dismissed: boolean;
    }) => {
      const artifactIds = group.versions.flatMap((version) =>
        version.id ? [version.id] : [],
      );
      if (artifactIds.length !== group.versions.length) {
        throw new Error("Artifact versions are still uploading");
      }
      return sessionService.setCloudRunArtifactsDismissed(
        taskId ?? "",
        runId ?? "",
        artifactIds,
        dismissed,
      );
    },
    // Overlay just the dismissal stamps from the response, so the row updates at once without
    // parking a whole-manifest snapshot over a source that keeps refreshing behind it.
    onSuccess: async (manifest) => {
      setDismissalOverrides((current) => ({
        ...current,
        ...Object.fromEntries(
          manifest.flatMap((entry) =>
            entry.id ? [[entry.id, entry.dismissed_at ?? null]] : [],
          ),
        ),
      }));
      const refreshed = await refetch();
      if (refreshed?.data) setDismissalOverrides({});
    },
    onError: () => toast.error("Couldn't update this file"),
  });

  if (!runId || groups.length === 0) return null;

  const renderRow = (group: ArtifactGroup) => {
    const pickedIndex = group.versions.findIndex(
      (version) =>
        runArtifactVersionKey(version) === selectedVersionByName[group.name],
    );
    const newestVisibleIndex = group.versions.findIndex(
      (version) => !version.dismissed_at,
    );
    const selectedIndex =
      pickedIndex >= 0 ? pickedIndex : Math.max(newestVisibleIndex, 0);
    const selected = group.versions[selectedIndex] as TaskRunArtifact;
    const size = formatFileSize(selected.size);
    const canDownload = Boolean(selected.id);
    const canChangeDismissal = group.versions.every((version) => version.id);

    const metaText = [
      uploaderLabel(selected, currentUser),
      selected.uploaded_at
        ? formatRelativeTimeLong(selected.uploaded_at)
        : null,
      size,
    ]
      .filter(Boolean)
      .join(" · ");

    return (
      // Compact take on the artifact pane's ArtifactCard (TaskArtifactsList):
      // role="button" because the version picker and trailing actions are real
      // buttons and HTML forbids nesting those.
      // biome-ignore lint/a11y/useSemanticElements: nested real buttons forbid a <button> card
      <div
        key={group.name}
        role="button"
        tabIndex={canDownload ? 0 : undefined}
        aria-disabled={canDownload ? undefined : true}
        aria-label={`View ${group.name}`}
        className={`flex w-full items-center gap-2.5 rounded-lg border border-border bg-muted py-1.5 pr-1.5 pl-2 text-[13px] transition-colors ${
          canDownload
            ? "cursor-pointer hover:border-gray-6 hover:bg-gray-3"
            : ""
        }`}
        onClick={() => {
          if (!taskId || !selected.id) return;
          openArtifactTab(taskId, {
            runId,
            artifactId: selected.id,
            name: selected.name,
          });
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (
            canDownload &&
            taskId &&
            selected.id &&
            (event.key === "Enter" || event.key === " ")
          ) {
            event.preventDefault();
            openArtifactTab(taskId, {
              runId,
              artifactId: selected.id,
              name: selected.name,
            });
          }
        }}
      >
        <div className="relative flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-gray-4">
          {/* The icon again, blown up and blurred: the tile tints itself with
              the icon's own colors, so new icons never need a color mapping. */}
          <div
            aria-hidden
            className="absolute inset-0 flex scale-[2.4] items-center justify-center opacity-40 blur-[9px] saturate-[1.8] dark:opacity-70"
          >
            <FileIcon filename={group.name} size={16} />
          </div>
          <div className="relative flex items-center justify-center">
            <FileIcon filename={group.name} size={16} />
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{group.name}</div>
          <div className="flex items-center gap-1 whitespace-nowrap text-[12px] text-muted-foreground">
            {metaText && <span className="truncate">{metaText}</span>}
            {group.versions.length > 1 && (
              <>
                {metaText && <span>·</span>}
                <DropdownMenu>
                  <DropdownMenuTrigger
                    render={
                      <button
                        type="button"
                        aria-label={`Choose a version of ${group.name}`}
                        onClick={(event) => event.stopPropagation()}
                        className="flex shrink-0 cursor-pointer items-center gap-0.5 text-foreground"
                      >
                        {versionShortLabel(
                          selectedIndex,
                          group.versions.length,
                        )}
                        <CaretDown size={10} />
                      </button>
                    }
                  />
                  {/* w-max: the default popup width tracks the anchor, and this
                      trigger is a couple of characters wide, so version labels
                      would be cut off. */}
                  <DropdownMenuContent align="start" className="w-max">
                    {group.versions.map((version, index) => (
                      <DropdownMenuItem
                        key={runArtifactVersionKey(version)}
                        onClick={() =>
                          setSelectedVersionByName((current) => ({
                            ...current,
                            [group.name]: runArtifactVersionKey(version),
                          }))
                        }
                      >
                        {versionMenuLabel(
                          version,
                          index,
                          group.versions.length,
                          currentUser,
                        )}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {group.dismissed ? (
            <Button
              size="sm"
              variant="outline"
              disabled={dismissal.isPending || !canChangeDismissal}
              onClick={(event) => {
                event.stopPropagation();
                dismissal.mutate({ group, dismissed: false });
              }}
            >
              Restore
            </Button>
          ) : (
            <>
              <Button
                size="icon-sm"
                variant="default"
                aria-label={`Download ${group.name}`}
                disabled={!canDownload || downloadingId !== null}
                onClick={(event) => {
                  event.stopPropagation();
                  if (!taskId || !selected.id) return;
                  void download({
                    taskId,
                    runId,
                    artifactId: selected.id,
                    name: selected.name,
                  });
                }}
              >
                <DownloadSimple size={14} />
              </Button>
              <Button
                size="icon-sm"
                variant="default"
                aria-label={`Dismiss ${group.name}`}
                disabled={dismissal.isPending || !canChangeDismissal}
                onClick={(event) => {
                  event.stopPropagation();
                  dismissal.mutate({ group, dismissed: true });
                }}
              >
                <X size={14} />
              </Button>
            </>
          )}
        </div>
      </div>
    );
  };

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="icon-sm"
            className="relative"
            aria-label={`Artifacts (${visibleGroups.length})`}
          >
            <Package size={16} />
            {visibleGroups.length > 0 && (
              <span className="-top-1 -right-1 absolute flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-primary px-0.5 font-semibold text-[9px] text-primary-foreground">
                {visibleGroups.length}
              </span>
            )}
          </Button>
        }
      />
      {/* quill's popup is a fixed 18rem; the rows carry name, size, age, and
          actions, which need the width the old inline card had. */}
      <PopoverContent
        side="top"
        align="end"
        sideOffset={6}
        className="w-[400px] max-w-[calc(100vw-2rem)] gap-2"
      >
        <div className="flex items-center justify-between">
          <span className="font-medium text-[13px] text-foreground">
            Artifacts
          </span>
          <span className="text-[12px] text-muted-foreground tabular-nums">
            {visibleGroups.length === 1
              ? "1 artifact"
              : `${visibleGroups.length} artifacts`}
          </span>
        </div>
        <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
          {visibleGroups.map(renderRow)}
          {showDismissed && dismissedGroups.map(renderRow)}
        </div>
        {dismissedGroups.length > 0 && (
          <Button
            size="sm"
            variant="link-muted"
            className="self-start"
            onClick={() => setShowDismissed((current) => !current)}
          >
            {showDismissed
              ? "Hide dismissed"
              : `Show ${dismissedGroups.length} dismissed`}
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}
