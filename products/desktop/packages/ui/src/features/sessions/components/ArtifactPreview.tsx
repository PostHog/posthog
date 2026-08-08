import { CrosshairSimpleIcon, XIcon } from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  groupRunArtifactVersions,
  runArtifactVersionKey,
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
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Spinner,
} from "@posthog/quill";
import { isAllowedImageMimeType, type TaskRunArtifact } from "@posthog/shared";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { useCommentsEnabled } from "@posthog/ui/features/sessions/useCommentsEnabled";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { CodeMirrorEditor } from "../../code-editor/components/CodeMirrorEditor";
import { DocumentPreviewHeader } from "../../code-editor/components/DocumentPreviewHeader";
import { MarkdownDocumentPreview } from "../../code-editor/components/MarkdownDocumentPreview";
import { AnnotatedArtifactHtml } from "./AnnotatedArtifactHtml";
import { AnnotatedArtifactImage } from "./AnnotatedArtifactImage";
import { ArtifactDocumentCommentAction } from "./ArtifactDocumentCommentAction";
import { ArtifactTextAnnotations } from "./ArtifactTextAnnotations";
import { artifactPreviewBlob } from "./artifactPreviewDocument";
import {
  buildCommentThreads,
  type CommentLocateRequest,
  type HighlightResolution,
} from "./commentViewTypes";
import { useCommentsQuery, useCreateComment } from "./useComments";

const MARKDOWN_EXTENSIONS = new Set(["md", "mdx", "markdown"]);
const HTML_EXTENSIONS = new Set(["html", "htm"]);
/** SVG is excluded from the shared image allowlist because its scripts can run
 *  when it comes from a data URL. An <img> renders SVG in a secure static mode
 *  that never runs scripts, so the zoom-and-annotate surface is safe for it. */
const SVG_MIME_TYPE = "image/svg+xml";
const EMPTY_COMMENTS: ResourceComment[] = [];

type HtmlPreview = { kind: "html"; html: string };
type PreviewData = string | Blob | HtmlPreview;
type EditableArtifactKind = "html" | "markdown" | "plain-text";

interface ArtifactPreviewResult {
  artifact: TaskRunArtifact;
  artifacts: TaskRunArtifact[];
  preview: PreviewData;
  source?: string;
}

interface SaveArtifactVariables {
  artifact: TaskRunArtifact;
  content: string;
}

function extension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

function editableArtifactKind(
  artifact: TaskRunArtifact,
): EditableArtifactKind | null {
  const contentType = artifact.content_type
    ?.split(";")[0]
    ?.trim()
    .toLowerCase();
  if (contentType === "text/markdown") return "markdown";
  if (contentType === "text/html") return "html";
  if (contentType === "text/plain") return "plain-text";
  if (contentType) return null;

  if (extension(artifact.name) === "md") return "markdown";
  if (extension(artifact.name) === "html") return "html";
  if (extension(artifact.name) === "txt") return "plain-text";
  return null;
}

function newestUndismissedVersion(
  artifacts: TaskRunArtifact[],
  name: string,
): TaskRunArtifact | undefined {
  const group = groupRunArtifactVersions(artifacts).find(
    (candidate) => candidate.name === name,
  );
  return group?.versions.find((version) => !version.dismissed_at);
}

function editorFilePath(kind: EditableArtifactKind, name: string): string {
  const expectedExtension =
    kind === "markdown" ? "md" : kind === "html" ? "html" : "txt";
  return extension(name) === expectedExtension
    ? name
    : `artifact.${expectedExtension}`;
}

function isArtifactPreviewResult(
  data: PreviewData | ArtifactPreviewResult | undefined,
): data is ArtifactPreviewResult {
  return Boolean(data && typeof data === "object" && "preview" in data);
}

function ArtifactPreviewError() {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      This artifact can’t be previewed.
    </div>
  );
}

function GenericArtifactHeader({
  name,
  actions,
}: {
  name: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-border border-b px-3">
      <span className="truncate font-[var(--code-font-family)] text-[13px] text-muted-foreground">
        {name}
      </span>
      {actions}
    </header>
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
}) {
  const commentsEnabled = useCommentsEnabled();
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const queryClient = useQueryClient();
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const [showRendered, setShowRendered] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [checkingLatest, setCheckingLatest] = useState(false);
  const [conflictOpen, setConflictOpen] = useState(false);
  const draftRef = useRef("");
  const editingBaseKeyRef = useRef<string | null>(null);
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
  const { data, isLoading, isError } = useQuery<
    PreviewData | ArtifactPreviewResult
  >({
    queryKey: ["artifactPreview", authIdentity, taskId, runId, artifactId],
    queryFn: async () => {
      const artifacts = await sessionService.getCloudRunArtifacts(
        taskId,
        runId,
      );
      const artifact = artifacts.find(
        (candidate) => candidate.id === artifactId,
      );
      if (!artifact) throw new Error("Artifact is unavailable");
      const url = await sessionService.getCloudAttachmentPreviewUrl(
        taskId,
        runId,
        artifactId,
      );
      if (!url) throw new Error("Artifact is unavailable");
      const response = await fetch(url);
      if (!response.ok) throw new Error("Artifact preview failed");
      const blob = await response.blob();
      const fileExtension = extension(name);
      const editableKind = editableArtifactKind(artifact);
      const needsSource =
        editableKind !== null || MARKDOWN_EXTENSIONS.has(fileExtension);
      const source = needsSource ? await blob.text() : undefined;
      let preview: PreviewData;
      if (
        editableKind === "markdown" ||
        MARKDOWN_EXTENSIONS.has(fileExtension)
      ) {
        preview = source ?? "";
      } else if (
        editableKind === "html" ||
        HTML_EXTENSIONS.has(fileExtension)
      ) {
        preview = { kind: "html", html: source ?? (await blob.text()) };
      } else {
        preview = await artifactPreviewBlob(blob, name);
      }
      return {
        artifact,
        artifacts,
        preview,
        ...(source === undefined ? {} : { source }),
      };
    },
    enabled: authIdentity !== null,
    staleTime: Infinity,
    retry: false,
    meta: AUTH_SCOPED_QUERY_META,
  });
  const previewData: PreviewData | undefined = isArtifactPreviewResult(data)
    ? data.preview
    : (data as PreviewData | undefined);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
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

  useEffect(() => {
    if (!(previewData instanceof Blob)) {
      setPreviewUrl(null);
      return;
    }
    const objectUrl = URL.createObjectURL(previewData);
    setPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [previewData]);

  /** This artifact's share of the task's focus, if the focus is on it at all. */
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

  const artifactResult = isArtifactPreviewResult(data) ? data : undefined;
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
      setConflictOpen(false);
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
    setConflictOpen(false);
    draftRef.current = "";
    editingBaseKeyRef.current = null;
  };

  const saveDraft = async (): Promise<void> => {
    if (!artifactResult || checkingLatest || saveArtifact.isPending) return;
    setCheckingLatest(true);
    let latest: TaskRunArtifact | undefined;
    try {
      const artifacts = await sessionService.getCloudRunArtifacts(
        taskId,
        runId,
      );
      latest = newestUndismissedVersion(
        artifacts,
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

    if (
      !latest ||
      runArtifactVersionKey(latest) !== editingBaseKeyRef.current
    ) {
      setConflictOpen(true);
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

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (isError || imageError) return <ArtifactPreviewError />;

  const editableKind = artifactResult
    ? editableArtifactKind(artifactResult.artifact)
    : null;
  const latest = artifactResult
    ? newestUndismissedVersion(
        artifactResult.artifacts,
        artifactResult.artifact.name,
      )
    : undefined;
  const canEdit = Boolean(
    editableKind &&
      artifactResult?.source !== undefined &&
      latest &&
      artifactResult &&
      runArtifactVersionKey(latest) ===
        runArtifactVersionKey(artifactResult.artifact),
  );
  const saving = checkingLatest || saveArtifact.isPending;

  if (isEditing && artifactResult?.source !== undefined && editableKind) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <DocumentPreviewHeader
          label={name}
          content={artifactResult.source}
          getContent={() => draftRef.current}
          showRendered={showRendered}
          editing
          saving={saving}
          onCancel={cancelEditing}
          onSave={() => void saveDraft()}
        />
        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          <CodeMirrorEditor
            content={artifactResult.source}
            filePath={editorFilePath(editableKind, name)}
            readOnly={false}
            onContentChange={(content) => {
              draftRef.current = content;
            }}
          />
        </div>
        <AlertDialog open={conflictOpen} onOpenChange={setConflictOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>A newer version is available</AlertDialogTitle>
              <AlertDialogDescription>
                A newer version of this file arrived while you were editing.
                Save yours as the latest anyway?
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogClose render={<Button variant="outline" />}>
                Keep editing
              </AlertDialogClose>
              <Button
                variant="primary"
                loading={saveArtifact.isPending}
                onClick={() => void forceSaveDraft()}
              >
                Save as latest
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    );
  }

  if (typeof previewData === "string") {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <DocumentPreviewHeader
          label={name}
          content={previewData}
          getContent={() => previewData}
          showRendered={showRendered}
          onToggleRendered={() => setShowRendered((rendered) => !rendered)}
          canEdit={canEdit}
          onEdit={beginEditing}
          actions={
            commentsEnabled ? (
              <ArtifactDocumentCommentAction
                target={commentTarget}
                taskId={taskId}
              />
            ) : undefined
          }
        />
        {commentLoadError}
        {showRendered ? (
          <div
            ref={markdownContainerRef}
            className="relative min-h-0 min-w-0 flex-1 overflow-auto"
          >
            <div ref={markdownRootRef}>
              <MarkdownDocumentPreview
                content={previewData}
                components={{ img: () => null }}
              />
            </div>
            {commentsEnabled && (
              <ArtifactTextAnnotations
                artifactName={name}
                rootRef={markdownRootRef}
                containerRef={markdownContainerRef}
                comments={annotationComments}
                activeThreadId={focusedThreadId}
                locateRequest={locateRequest}
                members={members}
                onActivateThread={activateThread}
                onCreate={createAnchoredComment}
                onResolutionsChange={onResolutionsChange}
              />
            )}
          </div>
        ) : (
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
            <CodeMirrorEditor content={previewData} filePath={name} readOnly />
          </div>
        )}
      </div>
    );
  }

  if (
    previewData &&
    !(previewData instanceof Blob) &&
    previewData.kind === "html"
  ) {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <DocumentPreviewHeader
          label={name}
          content={previewData.html}
          getContent={() => previewData.html}
          showRendered
          canEdit={canEdit}
          onEdit={beginEditing}
          actions={
            commentsEnabled ? (
              <ArtifactDocumentCommentAction
                target={commentTarget}
                taskId={taskId}
              />
            ) : undefined
          }
        />
        {commentLoadError}
        <div className="min-h-0 min-w-0 flex-1">
          <AnnotatedArtifactHtml
            html={previewData.html}
            name={name}
            commentsEnabled={commentsEnabled}
            comments={annotationComments}
            activeThreadId={focusedThreadId}
            locateRequest={locateRequest}
            members={members}
            onActivateThread={activateThread}
            onCreate={createAnchoredComment}
            onResolutionsChange={onResolutionsChange}
          />
        </div>
      </div>
    );
  }

  if (!previewData) return <ArtifactPreviewError />;
  if (previewData instanceof Blob && !previewUrl) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!previewUrl) return <ArtifactPreviewError />;

  if (
    previewData instanceof Blob &&
    (isAllowedImageMimeType(previewData.type) ||
      previewData.type === SVG_MIME_TYPE)
  ) {
    const imageActions = commentsEnabled ? (
      <div className="flex items-center gap-1">
        <ArtifactDocumentCommentAction target={commentTarget} taskId={taskId} />
        <Button
          size="sm"
          variant={imageCommenting ? "primary" : "outline"}
          onClick={() => setImageCommenting((commenting) => !commenting)}
        >
          {imageCommenting ? <XIcon /> : <CrosshairSimpleIcon />}
          {imageCommenting ? "Cancel" : "Pin comment…"}
        </Button>
      </div>
    ) : undefined;
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <GenericArtifactHeader name={name} actions={imageActions} />
        {commentLoadError}
        <div className="min-h-0 min-w-0 flex-1">
          <AnnotatedArtifactImage
            src={previewUrl}
            name={name}
            comments={annotationComments}
            activeThreadId={focusedThreadId}
            locateRequest={locateRequest}
            commenting={commentsEnabled && imageCommenting}
            members={members}
            onCommentingChange={setImageCommenting}
            onActivateThread={activateThread}
            onCreate={createAnchoredComment}
            onError={() => setImageError(true)}
          />
        </div>
      </div>
    );
  }

  const documentActions = commentsEnabled ? (
    <ArtifactDocumentCommentAction target={commentTarget} taskId={taskId} />
  ) : undefined;
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {editableKind === "plain-text" && artifactResult?.source !== undefined ? (
        <DocumentPreviewHeader
          label={name}
          content={artifactResult.source}
          getContent={() => artifactResult.source ?? ""}
          showRendered
          canEdit={canEdit}
          onEdit={beginEditing}
          actions={documentActions}
        />
      ) : (
        <GenericArtifactHeader name={name} actions={documentActions} />
      )}
      {commentLoadError}
      <div className="min-h-0 min-w-0 flex-1">
        <iframe
          className="h-full w-full border-0 bg-white"
          sandbox=""
          src={previewUrl}
          title={`Preview of ${name}`}
        />
      </div>
    </div>
  );
}
