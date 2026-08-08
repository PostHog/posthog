import type { ResourceComment } from "@posthog/api-client/posthog-client";
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
import { Spinner } from "@posthog/quill";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
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
import { useArtifactEditing } from "./useArtifactEditing";
import {
  editorFilePath,
  useArtifactPreviewData,
} from "./useArtifactPreviewData";
import { useCommentsQuery, useCreateComment } from "./useComments";

const EMPTY_COMMENTS: ResourceComment[] = [];

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
  const markdownRootRef = useRef<HTMLDivElement>(null);
  const markdownContainerRef = useRef<HTMLDivElement>(null);
  const [imageError, setImageError] = useState(false);
  const [imageCommenting, setImageCommenting] = useState(false);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const commentTarget = useMemo<CommentTarget>(
    () => ({ scope: "task_artifact", itemId: artifactId }),
    [artifactId],
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
  const { artifactResult, previewData, previewUrl, isLoading, isError } =
    useArtifactPreviewData({
      sessionService,
      authIdentity,
      taskId,
      runId,
      artifactId,
      name,
    });
  const editing = useArtifactEditing({
    sessionService,
    artifactResult,
    taskId,
    runId,
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
        conflictOpen={editing.conflictOpen}
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
