import { runArtifactVersionKey } from "@posthog/core/canvas/runArtifactSchemas";
import type { SessionService } from "@posthog/core/sessions/sessionService";
import type { TaskRunArtifact } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  type ArtifactPreviewResult,
  type EditableArtifactKind,
  editableArtifactKind,
  newestUndismissedVersion,
} from "./useArtifactPreviewData";

interface SaveArtifactVariables {
  artifact: TaskRunArtifact;
  content: string;
}

export type ArtifactEditConflict = "newer-version" | "dismissed";

export function useArtifactEditing({
  sessionService,
  artifactResult,
  versions,
  versionsLoading,
  refreshVersions,
  taskId,
  runId,
  name,
  authIdentity,
  openArtifactTab,
}: {
  sessionService: SessionService;
  artifactResult: ArtifactPreviewResult | undefined;
  versions: TaskRunArtifact[];
  versionsLoading: boolean;
  refreshVersions: () => Promise<TaskRunArtifact[]>;
  taskId: string;
  runId: string;
  name: string;
  authIdentity: string | null;
  openArtifactTab: (
    taskId: string,
    artifact: { runId: string; artifactId: string; name: string },
  ) => void;
}): {
  editableKind: EditableArtifactKind | null;
  canEdit: boolean;
  isEditing: boolean;
  saving: boolean;
  conflict: ArtifactEditConflict | null;
  setConflictOpen: (open: boolean) => void;
  beginEditing: () => void;
  cancelEditing: () => void;
  saveDraft: () => Promise<void>;
  forceSaveDraft: () => Promise<void>;
  getDraftContent: () => string;
  setDraftContent: (content: string) => void;
} {
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [checkingLatest, setCheckingLatest] = useState(false);
  const [conflict, setConflict] = useState<ArtifactEditConflict | null>(null);
  const draftRef = useRef("");
  const editingBaseKeyRef = useRef<string | null>(null);
  const editableKind = artifactResult
    ? editableArtifactKind(artifactResult.artifact)
    : null;
  const latest = artifactResult
    ? newestUndismissedVersion(versions, artifactResult.artifact.name)
    : undefined;
  const canEdit = Boolean(
    editableKind &&
      !versionsLoading &&
      artifactResult?.source !== undefined &&
      latest &&
      artifactResult &&
      runArtifactVersionKey(latest) ===
        runArtifactVersionKey(artifactResult.artifact),
  );

  const saveArtifact = useMutation({
    mutationFn: (variables: SaveArtifactVariables) =>
      sessionService.uploadCloudRunArtifactVersion(
        taskId,
        runId,
        variables.artifact.name,
        variables.content,
        variables.artifact.content_type,
      ),
    onSuccess: async (savedArtifactId) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["cloudRunArtifacts", authIdentity, taskId, runId],
        }),
        queryClient.invalidateQueries({ queryKey: ["task-runs", taskId] }),
      ]);
      setConflict(null);
      setIsEditing(false);
      openArtifactTab(taskId, {
        runId,
        artifactId: savedArtifactId,
        name,
      });
    },
    onError: () =>
      toast.error("Couldn't save file", {
        description: "Try again. Your changes are still in the editor.",
      }),
  });

  const beginEditing = (): void => {
    if (!artifactResult || artifactResult.source === undefined) return;
    draftRef.current = artifactResult.source;
    editingBaseKeyRef.current = runArtifactVersionKey(artifactResult.artifact);
    setIsEditing(true);
  };

  const cancelEditing = (): void => {
    setIsEditing(false);
    setConflict(null);
    draftRef.current = "";
    editingBaseKeyRef.current = null;
  };

  const saveDraft = async (): Promise<void> => {
    if (!artifactResult || checkingLatest || saveArtifact.isPending) return;
    setCheckingLatest(true);
    let currentLatest: TaskRunArtifact | undefined;
    try {
      const refreshedVersions = await refreshVersions();
      currentLatest = newestUndismissedVersion(
        refreshedVersions,
        artifactResult.artifact.name,
      );
    } catch {
      toast.error("Couldn't check the latest file version", {
        description: "Try saving again. Your changes are still in the editor.",
      });
      return;
    } finally {
      setCheckingLatest(false);
    }

    if (!currentLatest) {
      setConflict("dismissed");
      return;
    }
    if (runArtifactVersionKey(currentLatest) !== editingBaseKeyRef.current) {
      setConflict("newer-version");
      return;
    }
    try {
      await saveArtifact.mutateAsync({
        artifact: artifactResult.artifact,
        content: draftRef.current,
      });
    } catch {
      return;
    }
  };

  const forceSaveDraft = async (): Promise<void> => {
    if (!artifactResult || saveArtifact.isPending) return;
    try {
      await saveArtifact.mutateAsync({
        artifact: artifactResult.artifact,
        content: draftRef.current,
      });
    } catch {
      return;
    }
  };

  return {
    editableKind,
    canEdit,
    isEditing,
    saving: checkingLatest || saveArtifact.isPending,
    conflict,
    setConflictOpen: (open) => {
      if (!open) setConflict(null);
    },
    beginEditing,
    cancelEditing,
    saveDraft,
    forceSaveDraft,
    getDraftContent: () => draftRef.current,
    setDraftContent: (content) => {
      draftRef.current = content;
    },
  };
}
