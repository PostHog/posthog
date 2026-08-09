import { CaretLeftIcon, CaretRightIcon } from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  groupRunArtifactVersions,
  OUTPUT_ARTIFACT_TYPES,
  parseRunArtifacts,
} from "@posthog/core/canvas/runArtifactSchemas";
import {
  type CommentAnchor,
  type CommentTarget,
  isSameCommentTarget,
} from "@posthog/core/comments/anchors";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { Button, Spinner } from "@posthog/quill";
import type { TaskRun, TaskRunArtifact } from "@posthog/shared";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import { useCommentsEnabled } from "@posthog/ui/features/sessions/useCommentsEnabled";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ArtifactEditView } from "./ArtifactEditView";
import {
  ArtifactPreviewContent,
  ArtifactPreviewError,
} from "./ArtifactPreviewContent";
import {
  buildCommentThreads,
  type CommentLocateRequest,
  type HighlightResolution,
} from "./commentViewTypes";
import { useCompletedArtifactUploads } from "./countArtifactUploads";
import { useArtifactEditing } from "./useArtifactEditing";
import {
  editorFilePath,
  useArtifactPreviewData,
} from "./useArtifactPreviewData";
import { useCommentsQuery, useCreateComment } from "./useComments";

const EMPTY_COMMENTS: ResourceComment[] = [];

type ArtifactVersion = TaskRunArtifact & { runId: string };

function artifactVersionsFromRuns(
  runs: TaskRun[],
  name: string,
): ArtifactVersion[] {
  const files = runs.flatMap((run) =>
    parseRunArtifacts(run.artifacts, OUTPUT_ARTIFACT_TYPES).flatMap((file) =>
      file.name === name && file.id
        ? [
            {
              ...file,
              id: file.id,
              name: file.name,
              type: file.type as TaskRunArtifact["type"],
              runId: run.id,
            },
          ]
        : [],
    ),
  );
  return (
    groupRunArtifactVersions(files).find((candidate) => candidate.name === name)
      ?.versions ?? []
  );
}

/** The artifact is the whole pane: its threads are listed in the task's
 *  Comments tab, and this only renders and locates their anchors. */
export function ArtifactPreview({
  taskId,
  runId,
  artifactId,
  name,
}: {
  taskId: string;
  runId: string;
  artifactId: string;
  name: string;
}): ReactElement {
  const commentsEnabled = useCommentsEnabled();
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const [showRendered, setShowRendered] = useState(true);
  // Every version of this file across the task's runs, newest first - the
  // same grouping the artifact list shows. Stepping through them swaps what
  // this tab renders without opening more tabs. A finished upload_artifact
  // tool call re-keys the runs query so a just-delivered version is steppable
  // right away.
  const events = useSessionSelector(taskId, (session) => session?.events);
  const completedUploads = useCompletedArtifactUploads(events ?? []);
  const {
    runs,
    isLoading: runsLoading,
    refreshRuns,
  } = useTaskRuns(taskId, completedUploads);
  const versions = useMemo(
    () => artifactVersionsFromRuns(runs, name),
    [runs, name],
  );
  const refreshVersions = useCallback(async (): Promise<ArtifactVersion[]> => {
    return artifactVersionsFromRuns(await refreshRuns(), name);
  }, [name, refreshRuns]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    null,
  );
  const activeArtifactId = selectedVersionId ?? artifactId;
  const activeVersionIndex = versions.findIndex(
    (version) => version.id === activeArtifactId,
  );
  const activeRunId =
    activeVersionIndex >= 0
      ? (versions[activeVersionIndex]?.runId ?? runId)
      : runId;
  const markdownRootRef = useRef<HTMLDivElement>(null);
  const markdownContainerRef = useRef<HTMLDivElement>(null);
  const [imageError, setImageError] = useState(false);
  const [imageCommenting, setImageCommenting] = useState(false);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const {
    artifactResult,
    previewData,
    previewUrl,
    isLoading,
    isError,
    isPlaceholderData,
  } = useArtifactPreviewData({
    sessionService,
    authIdentity,
    taskId,
    runId: activeRunId,
    artifactId: activeArtifactId,
    name,
  });
  const displayedArtifactId = artifactResult?.artifact.id ?? activeArtifactId;
  const versionIndex = versions.findIndex(
    (version) => version.id === displayedArtifactId,
  );
  const displayedRunId =
    versionIndex >= 0 ? (versions[versionIndex]?.runId ?? runId) : runId;
  const commentTarget = useMemo<CommentTarget>(
    () => ({ scope: "task_artifact", itemId: displayedArtifactId }),
    [displayedArtifactId],
  );
  const commentsQuery = useCommentsQuery(commentTarget, taskId, {
    enabled: commentsEnabled,
  });
  const { members } = useOrgMembers({ enabled: commentsEnabled });
  const createComment = useCreateComment(commentTarget, taskId);
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );
  const setCommentResolutions = useCommentNavigationStore(
    (state) => state.setCommentResolutions,
  );
  const focus = useCommentNavigationStore((state) => state.focusByTask[taskId]);
  useEffect(() => {
    if (
      !focus ||
      focus.target.scope !== "task_artifact" ||
      focus.target.itemId === activeArtifactId ||
      !versions.some((version) => version.id === focus.target.itemId)
    ) {
      return;
    }
    setSelectedVersionId(focus.target.itemId);
  }, [activeArtifactId, focus, versions]);
  const editing = useArtifactEditing({
    sessionService,
    artifactResult,
    versions:
      versions.length > 0 ? versions : (artifactResult?.artifacts ?? []),
    versionsLoading: runsLoading || isPlaceholderData,
    refreshVersions,
    taskId,
    runId: displayedRunId,
    name,
    authIdentity,
    openArtifactTab,
  });
  const comments = commentsEnabled
    ? (commentsQuery.data ?? EMPTY_COMMENTS)
    : EMPTY_COMMENTS;
  const commentLoadError = commentsEnabled && commentsQuery.isError && (
    <div
      role="alert"
      className="shrink-0 border-amber-6 border-b bg-amber-2 px-3 py-2 text-amber-12 text-xs"
    >
      Couldn't load comments. Refresh to try again.
    </div>
  );
  const threads = useMemo(() => buildCommentThreads(comments), [comments]);
  const openRootComments = useMemo(
    () => threads.flatMap((thread) => (thread.resolved ? [] : [thread.root])),
    [threads],
  );
  const focusedThreadId =
    focus && isSameCommentTarget(focus.target, commentTarget)
      ? focus.threadId
      : null;
  const annotationComments = useMemo(() => {
    const focusedResolvedRoot = threads.find(
      (thread) => thread.resolved && thread.root.id === focusedThreadId,
    )?.root;
    return focusedResolvedRoot
      ? [...openRootComments, focusedResolvedRoot]
      : openRootComments;
  }, [focusedThreadId, openRootComments, threads]);
  // The locate request only fires once the thread exists, so it survives the
  // comments arriving after the request — and re-fires when the nonce moves,
  // which is how picking the same thread twice scrolls twice.
  const [locateRequest, setLocateRequest] =
    useState<CommentLocateRequest | null>(null);
  useEffect(() => {
    if (!focus || !focusedThreadId) return;
    if (!threads.some((thread) => thread.root.id === focusedThreadId)) return;
    setLocateRequest((current) =>
      current?.nonce === focus.nonce
        ? current
        : { id: focusedThreadId, nonce: focus.nonce },
    );
  }, [focus, focusedThreadId, threads]);

  const activateThread = useCallback(
    (id: string) => requestCommentFocus(taskId, commentTarget, id),
    [requestCommentFocus, taskId, commentTarget],
  );
  const onResolutionsChange = useCallback(
    (resolutions: Map<string, HighlightResolution>) =>
      setCommentResolutions(commentTarget, resolutions),
    [setCommentResolutions, commentTarget],
  );
  const createAnchoredComment = useCallback(
    async (anchor: CommentAnchor, content: string, mentions: number[] = []) => {
      const created = await createComment.mutateAsync({
        content,
        context: { anchor },
        mentions,
      });
      activateThread(created.id);
    },
    [createComment, activateThread],
  );

  const versionNav =
    versions.length > 1 && versionIndex >= 0 ? (
      <div className="flex shrink-0 items-center gap-0.5">
        <Button
          size="icon"
          variant="default"
          aria-label="Older version"
          disabled={isPlaceholderData || versionIndex >= versions.length - 1}
          onClick={() => {
            const older = versions[versionIndex + 1];
            if (older?.id) setSelectedVersionId(older.id);
          }}
        >
          <CaretLeftIcon size={12} />
        </Button>
        <span className="text-[11px] text-muted-foreground tabular-nums">
          v{versions.length - versionIndex}/{versions.length}
        </span>
        <Button
          size="icon"
          variant="default"
          aria-label="Newer version"
          disabled={isPlaceholderData || versionIndex <= 0}
          onClick={() => {
            const newer = versions[versionIndex - 1];
            if (newer?.id) setSelectedVersionId(newer.id);
          }}
        >
          <CaretRightIcon size={12} />
        </Button>
      </div>
    ) : null;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (isError || imageError) return <ArtifactPreviewError />;

  if (
    editing.isEditing &&
    artifactResult?.source !== undefined &&
    editing.editableKind
  ) {
    return (
      <ArtifactEditView
        name={name}
        source={artifactResult.source}
        editorPath={editorFilePath(editing.editableKind, name)}
        showRendered={showRendered}
        saving={editing.saving}
        conflict={editing.conflict}
        onConflictOpenChange={editing.setConflictOpen}
        getContent={editing.getDraftContent}
        onContentChange={editing.setDraftContent}
        onCancel={editing.cancelEditing}
        onSave={() => void editing.saveDraft()}
        onForceSave={() => void editing.forceSaveDraft()}
      />
    );
  }

  return (
    <ArtifactPreviewContent
      name={name}
      versionNav={versionNav}
      taskId={taskId}
      commentTarget={commentTarget}
      commentsEnabled={commentsEnabled}
      canEdit={editing.canEdit}
      beginEditing={editing.beginEditing}
      previewData={previewData}
      previewUrl={previewUrl}
      showRendered={showRendered}
      setShowRendered={setShowRendered}
      commentLoadError={commentLoadError}
      markdownRootRef={markdownRootRef}
      markdownContainerRef={markdownContainerRef}
      annotationComments={annotationComments}
      focusedThreadId={focusedThreadId}
      locateRequest={locateRequest}
      members={members}
      activateThread={activateThread}
      createAnchoredComment={createAnchoredComment}
      onResolutionsChange={onResolutionsChange}
      imageCommenting={imageCommenting}
      setImageCommenting={setImageCommenting}
      onImageError={() => setImageError(true)}
      editableKind={editing.editableKind}
      artifactResult={artifactResult}
    />
  );
}
