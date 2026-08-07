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
import { formatRelativeTimeLong, type TaskRunArtifact } from "@posthog/shared";
import { isTerminalStatus, type Task } from "@posthog/shared/domain-types";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import {
  useArtifactFilesCollapsed,
  useSessionViewActions,
} from "@posthog/ui/features/sessions/sessionViewStore";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { toast } from "@posthog/ui/primitives/toast";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

type ArtifactGroup = RunArtifactVersions<TaskRunArtifact>;

function versionMenuLabel(
  artifact: TaskRunArtifact,
  index: number,
  total: number,
): string {
  const label = runArtifactVersionLabel(index, total);
  return artifact.uploaded_at
    ? `${label} · ${formatRelativeTimeLong(artifact.uploaded_at)}`
    : label;
}

export function CloudArtifactDownloads({
  taskId,
  task,
}: {
  taskId: string | undefined;
  task: Task | undefined;
}) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
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
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [selectedVersionByName, setSelectedVersionByName] = useState<
    Record<string, string>
  >({});
  const [showDismissed, setShowDismissed] = useState(false);
  const runId = task?.latest_run?.id;
  const artifactsQueryKey = ["cloudRunArtifacts", authIdentity, taskId, runId];
  const { data: fetchedArtifacts } = useQuery({
    queryKey: artifactsQueryKey,
    queryFn: () =>
      sessionService.getCloudRunArtifacts(taskId ?? "", runId ?? ""),
    enabled:
      authIdentity !== null &&
      taskId !== undefined &&
      runId !== undefined &&
      isTerminalStatus(cloudStatus ?? task?.latest_run?.status),
    retry: false,
    staleTime: Infinity,
  });
  const groups = useMemo(
    () =>
      groupRunArtifactVersions(
        (
          fetchedArtifacts ??
          sessionArtifacts ??
          task?.latest_run?.artifacts ??
          []
        ).filter((artifact) => artifact.type === "output"),
      ),
    [fetchedArtifacts, sessionArtifacts, task?.latest_run?.artifacts],
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
    }) =>
      sessionService.setCloudRunArtifactsDismissed(
        taskId ?? "",
        runId ?? "",
        group.versions.flatMap((version) => version.id ?? []),
        dismissed,
      ),
    // The response carries the whole manifest, so the rows re-render from it
    // even while the query itself is disabled for a run that is still going.
    onSuccess: (manifest) =>
      queryClient.setQueryData(artifactsQueryKey, manifest),
    onError: () => toast.error("Couldn't update this file"),
  });

  const downloadArtifact = useCallback(
    async (artifact: TaskRunArtifact): Promise<void> => {
      if (!taskId || !runId || !artifact.id) return;
      setDownloadingId(artifact.id);
      try {
        const url = await sessionService.getCloudAttachmentPreviewUrl(
          taskId,
          runId,
          artifact.id,
        );
        if (!url) {
          toast.error("This file is no longer available");
          return;
        }
        const response = await fetch(url);
        if (!response.ok) throw new Error("Artifact download failed");
        const objectUrl = URL.createObjectURL(await response.blob());
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = artifact.name;
        anchor.click();
        URL.revokeObjectURL(objectUrl);
      } catch {
        toast.error("Couldn't download file");
      } finally {
        setDownloadingId(null);
      }
    },
    [runId, sessionService, taskId],
  );

  if (!runId || groups.length === 0) return null;

  const renderRow = (group: ArtifactGroup) => {
    const selectedIndex = Math.max(
      group.versions.findIndex(
        (version) => version.id === selectedVersionByName[group.name],
      ),
      0,
    );
    const selected = group.versions[selectedIndex] as TaskRunArtifact;
    const size = formatFileSize(selected.size);
    const canDownload = Boolean(selected.id);

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
                      [group.name]: version.id ?? "",
                    }))
                  }
                >
                  {versionMenuLabel(version, index, group.versions.length)}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        {group.dismissed ? (
          <Button
            size="sm"
            variant="outline"
            disabled={dismissal.isPending}
            onClick={() => dismissal.mutate({ group, dismissed: false })}
          >
            Restore
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              variant="outline"
              disabled={!canDownload || downloadingId === selected.id}
              onClick={() => void downloadArtifact(selected)}
            >
              <DownloadSimple size={14} />
              {downloadingId === selected.id ? "Opening..." : "Download"}
            </Button>
            <Button
              size="icon-sm"
              variant="outline"
              aria-label={`Dismiss ${group.name}`}
              disabled={dismissal.isPending}
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
