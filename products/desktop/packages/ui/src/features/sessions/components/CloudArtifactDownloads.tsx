import { Collapsible } from "@base-ui/react/collapsible";
import {
  CaretDown,
  CaretRight,
  DownloadSimple,
  X,
} from "@phosphor-icons/react";
import {
  groupRunArtifactVersions,
  type RunArtifactVersions,
  runArtifactVersionKey,
  runArtifactVersionLabel,
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
  Text,
} from "@posthog/quill";
import { formatRelativeTimeShort, type TaskRunArtifact } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import {
  useArtifactFilesCollapsed,
  useSessionViewActions,
} from "@posthog/ui/features/sessions/sessionViewStore";
import { useArtifactDownload } from "@posthog/ui/features/sessions/useArtifactDownload";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { toast } from "@posthog/ui/primitives/toast";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useCompletedArtifactUploads } from "./countArtifactUploads";

type ArtifactGroup = RunArtifactVersions<TaskRunArtifact>;

/**
 * The menu sits at the right edge of the thread, and its popup is capped at the space left
 * there and clips what does not fit, so the age is the compact form rather than the row's.
 */
function wasEditedByCurrentUser(
  artifact: TaskRunArtifact,
  currentUserId: number | undefined,
): boolean {
  return (
    artifact.uploaded_by === "user" &&
    currentUserId !== undefined &&
    artifact.uploaded_by_user_id === currentUserId
  );
}

function versionMenuLabel(
  artifact: TaskRunArtifact,
  index: number,
  total: number,
  currentUserId: number | undefined,
): string {
  return [
    runArtifactVersionLabel(index, total),
    wasEditedByCurrentUser(artifact, currentUserId) ? "Edited by you" : null,
    artifact.uploaded_at ? formatRelativeTimeShort(artifact.uploaded_at) : null,
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
  const collapsed = useArtifactFilesCollapsed(taskId);
  const { setArtifactFilesCollapsed } = useSessionViewActions();
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

  const groups = useMemo(
    () =>
      groupRunArtifactVersions(
        (
          fetchedArtifacts ??
          sessionArtifacts ??
          task?.latest_run?.artifacts ??
          []
        ).flatMap((artifact) => {
          if (artifact.type !== "output") return [];
          return [
            artifact.id && artifact.id in dismissalOverrides
              ? { ...artifact, dismissed_at: dismissalOverrides[artifact.id] }
              : artifact,
          ];
        }),
      ),
    [
      dismissalOverrides,
      fetchedArtifacts,
      sessionArtifacts,
      task?.latest_run?.artifacts,
    ],
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

    return (
      <div
        key={group.name}
        className="flex min-w-0 items-center justify-between gap-2 rounded-md bg-background px-2 py-1.5"
      >
        <button
          type="button"
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left"
          disabled={!canDownload}
          onClick={() => {
            if (!taskId || !selected.id) return;
            openArtifactTab(taskId, {
              runId,
              artifactId: selected.id,
              name: selected.name,
            });
          }}
        >
          <FileIcon filename={selected.name} size={16} />
          <Text className="truncate text-[13px]">{selected.name}</Text>
          {size !== null && (
            <Text className="shrink-0 text-[12px] text-gray-10">{size}</Text>
          )}
          {wasEditedByCurrentUser(selected, currentUser?.id) && (
            <Text className="shrink-0 text-[12px] text-gray-10">
              Edited by you
            </Text>
          )}
          <RelativeTimestamp timestamp={selected.uploaded_at} />
        </button>
        {group.versions.length > 1 && (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  size="sm"
                  variant="outline"
                  aria-label={`Choose a version of ${group.name}`}
                >
                  {runArtifactVersionLabel(
                    selectedIndex,
                    group.versions.length,
                  )}
                  <CaretDown size={12} />
                </Button>
              }
            />
            <DropdownMenuContent align="end">
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
                    currentUser?.id,
                  )}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {group.dismissed ? (
          <Button
            size="sm"
            variant="outline"
            disabled={dismissal.isPending || !canChangeDismissal}
            onClick={() => dismissal.mutate({ group, dismissed: false })}
          >
            Restore
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              variant="outline"
              disabled={!canDownload || downloadingId !== null}
              onClick={() => {
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
              {downloadingId === selected.id ? "Opening..." : "Download"}
            </Button>
            <Button
              size="icon-sm"
              variant="outline"
              aria-label={`Dismiss ${group.name}`}
              disabled={dismissal.isPending || !canChangeDismissal}
              onClick={() => dismissal.mutate({ group, dismissed: true })}
            >
              <X size={14} />
            </Button>
          </>
        )}
      </div>
    );
  };

  return (
    // Base UI rather than quill's Collapsible: quill styles the root/trigger
    // as a standalone disclosure row (hover/selected fills on the whole
    // padded header), which reads as a misplaced selected block inside this
    // already-bordered card — see ChannelsList for the same call.
    <Collapsible.Root
      open={!collapsed}
      onOpenChange={(open) => {
        if (taskId) setArtifactFilesCollapsed(taskId, !open);
      }}
      className="mb-3 rounded-lg border border-gray-4 bg-gray-2 p-3"
    >
      <Collapsible.Trigger className="flex w-full cursor-pointer items-center gap-1.5 text-left font-medium text-[13px]">
        {collapsed ? <CaretRight size={12} /> : <CaretDown size={12} />}
        Files ({visibleGroups.length})
      </Collapsible.Trigger>
      <Collapsible.Panel className="mt-2">
        <div className="flex flex-col gap-1">
          {visibleGroups.map(renderRow)}
          {showDismissed && dismissedGroups.map(renderRow)}
        </div>
        {dismissedGroups.length > 0 && (
          <Button
            size="sm"
            variant="link-muted"
            className="mt-1"
            onClick={() => setShowDismissed((current) => !current)}
          >
            {showDismissed
              ? "Hide dismissed"
              : `Show ${dismissedGroups.length} dismissed`}
          </Button>
        )}
      </Collapsible.Panel>
    </Collapsible.Root>
  );
}
