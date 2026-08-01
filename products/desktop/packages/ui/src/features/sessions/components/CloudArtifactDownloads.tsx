import { DownloadSimple } from "@phosphor-icons/react";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { Button } from "@posthog/quill";
import type { TaskRunArtifact } from "@posthog/shared";
import { isTerminalStatus, type Task } from "@posthog/shared/domain-types";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { toast } from "@posthog/ui/primitives/toast";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

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
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const runId = task?.latest_run?.id;
  const { data: fetchedArtifacts } = useQuery({
    queryKey: ["cloudRunArtifacts", authIdentity, taskId, runId],
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
  const artifacts = useMemo(
    () =>
      (
        fetchedArtifacts ??
        sessionArtifacts ??
        task?.latest_run?.artifacts ??
        []
      ).filter((artifact) => artifact.type === "output"),
    [fetchedArtifacts, sessionArtifacts, task?.latest_run?.artifacts],
  );

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

  if (!runId || artifacts.length === 0) return null;

  return (
    <Box className="mb-3 rounded-lg border border-gray-4 bg-gray-2 p-3">
      <Text className="mb-2 block font-medium text-[13px]">Files</Text>
      <Flex direction="column" gap="1">
        {artifacts.map((artifact) => {
          const size = formatFileSize(artifact.size);
          const canDownload = Boolean(artifact.id);
          return (
            <Flex
              key={artifact.id ?? artifact.storage_path ?? artifact.name}
              align="center"
              justify="between"
              gap="3"
              className="min-w-0 rounded-md bg-background px-2 py-1.5"
            >
              <button
                type="button"
                className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left"
                disabled={!canDownload}
                onClick={() => {
                  if (!taskId || !artifact.id) return;
                  openArtifactTab(taskId, {
                    runId,
                    artifactId: artifact.id,
                    name: artifact.name,
                  });
                }}
              >
                <FileIcon filename={artifact.name} size={16} />
                <Text className="truncate text-[13px]">{artifact.name}</Text>
                {size !== null && (
                  <Text color="gray" className="shrink-0 text-[12px]">
                    {size}
                  </Text>
                )}
              </button>
              <Button
                size="sm"
                variant="outline"
                disabled={!canDownload || downloadingId === artifact.id}
                onClick={() => void downloadArtifact(artifact)}
              >
                <DownloadSimple size={14} />
                {downloadingId === artifact.id ? "Opening..." : "Download"}
              </Button>
            </Flex>
          );
        })}
      </Flex>
    </Box>
  );
}
