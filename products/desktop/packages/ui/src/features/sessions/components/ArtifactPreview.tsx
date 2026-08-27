import { CaretLeftIcon, CaretRightIcon } from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  getPostHogObjectArtifactMetadata,
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
import { PostHogObjectPage } from "@posthog/ui/features/posthog-objects/PostHogObjectPage";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
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
  type PostHogObjectPreview,
  type PreviewData,
  useArtifactPreviewData,
} from "./useArtifactPreviewData";
import { useCommentsQuery, useCreateComment } from "./useComments";

const EMPTY_COMMENTS: ResourceComment[] = [];

function isPostHogObjectPreview(
  previewData: PreviewData | undefined,
): previewData is PostHogObjectPreview {
  return (
    !!previewData &&
    typeof previewData === "object" &&
    !(previewData instanceof Blob) &&
    previewData.kind === "posthog-object"
  );
}

type ArtifactVersion = TaskRunArtifact & { runId: string };

function artifactVersionsFromRuns(
  runs: TaskRun[],
  name: string,
): ArtifactVersion[] {
  const files = runs.flatMap((run) =>
    parseRunArtifacts(run.artifacts, OUTPUT_ARTIFACT_TYPES).flatMap((file) => {
      if (file.name !== name || !file.id) return [];
      const { metadata: _metadata, ...fileFields } = file;
      return [
        {
          ...fileFields,
          id: file.id,
          name: file.name,
          type: file.type as TaskRunArtifact["type"],
          runId: run.id,
        },
      ];
    }),
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
  // The preview query caches forever under a stable artifact id, but a
  // reference entry updates in place as later turns cite it again; the store's
  // cloudArtifacts refresh on every successful registration, so its copy of
  // the metadata is the live one.
  const liveReferenceMetadata = useSessionSelector(taskId, (session) => {
    const entry = session?.cloudArtifacts?.find(
      (artifact) => artifact.id === artifactId,
    );
    return entry ? getPostHogObjectArtifactMetadata(entry) : null;
  });
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
  // An object reference renders its own page below and uses none of the
  // file-only comment data, so its tab shouldn't run the comments poll.
  const isObjectPreview = isPostHogObjectPreview(previewData);
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
    enabled: !isObjectPreview,
  });
  const { members } = useOrgMembers();
  const createComment = useCreateComment(commentTarget, taskId);
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );
  const setCommentResolutions = useCommentNavigationStore(
    (state) => state.setCommentResolutions,
  );
  const focus = useCommentNavigationStore((state) => state.focusByTask[taskId]);
  // Take each request once: focus is durable, so otherwise stepping the pager
  // off a commented version snaps straight back to it.
  const takenNonce = useRef<number | null>(null);
  useEffect(() => {
    if (
      !focus ||
      focus.target.scope !== "task_artifact" ||
      takenNonce.current === focus.nonce ||
      !versions.some((version) => version.id === focus.target.itemId)
    ) {
      return;
    }
    takenNonce.current = focus.nonce;
    setSelectedVersionId(focus.target.itemId);
  }, [focus, versions]);
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
  const comments = commentsQuery.data ?? EMPTY_COMMENTS;
  const commentLoadError = commentsQuery.isError && (
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
    if (!focus || !focusedThreadId || focus.intent !== "navigate") return;
    if (!threads.some((thread) => thread.root.id === focusedThreadId)) return;
    setLocateRequest((current) =>
      current?.nonce === focus.nonce
        ? current
        : { id: focusedThreadId, nonce: focus.nonce },
    );
  }, [focus, focusedThreadId, threads]);
  const currentLocateRequest =
    focus &&
    focus.intent === "navigate" &&
    focusedThreadId &&
    locateRequest?.nonce === focus.nonce
      ? locateRequest
      : null;

  const activateThread = useCallback(
    (id: string) =>
      requestCommentFocus(taskId, commentTarget, id, {
        intent: "reveal-thread",
      }),
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
      requestCommentFocus(taskId, commentTarget, created.id, {
        intent: "focus-only",
      });
    },
    [commentTarget, createComment, requestCommentFocus, taskId],
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

  if (isPostHogObjectPreview(previewData)) {
    return (
      <PostHogObjectPage
        metadata={liveReferenceMetadata ?? previewData.metadata}
        fallbackName={name}
      />
    );
  }

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
      locateRequest={currentLocateRequest}
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
