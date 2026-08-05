import { CrosshairSimpleIcon, XIcon } from "@phosphor-icons/react";
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
import { Button, Spinner } from "@posthog/quill";
import { isAllowedImageMimeType } from "@posthog/shared";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { useQuery } from "@tanstack/react-query";
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

function extension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
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
  const sessionService = useService<SessionService>(SESSION_SERVICE);
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
  const commentsQuery = useCommentsQuery(commentTarget);
  const { members } = useOrgMembers();
  const createComment = useCreateComment(commentTarget, taskId);
  const requestCommentFocus = useCommentNavigationStore(
    (state) => state.requestCommentFocus,
  );
  const setCommentResolutions = useCommentNavigationStore(
    (state) => state.setCommentResolutions,
  );
  const focus = useCommentNavigationStore((state) => state.focusByTask[taskId]);
  const { data, isLoading, isError } = useQuery<PreviewData>({
    queryKey: ["artifactPreview", authIdentity, taskId, runId, artifactId],
    queryFn: async () => {
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
      if (MARKDOWN_EXTENSIONS.has(fileExtension)) return blob.text();
      if (HTML_EXTENSIONS.has(fileExtension)) {
        return { kind: "html", html: await blob.text() };
      }
      return artifactPreviewBlob(blob, name);
    },
    enabled: authIdentity !== null,
    staleTime: Infinity,
    retry: false,
    meta: AUTH_SCOPED_QUERY_META,
  });
  const previewUrl = useMemo(
    () => (data instanceof Blob ? URL.createObjectURL(data) : null),
    [data],
  );
  const comments = commentsQuery.data ?? EMPTY_COMMENTS;
  const threads = useMemo(() => buildCommentThreads(comments), [comments]);
  const openRootComments = useMemo(
    () => threads.flatMap((thread) => (thread.resolved ? [] : [thread.root])),
    [threads],
  );

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  /** This artifact's share of the task's focus, if the focus is on it at all. */
  const focusedThreadId =
    focus && isSameCommentTarget(focus.target, commentTarget)
      ? focus.threadId
      : null;
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
    (anchor: CommentAnchor, content: string, mentions: number[] = []) => {
      createComment.mutate(
        { content, context: { anchor }, mentions },
        // With no thread list in this pane, focusing the new thread is what
        // tells the user it landed — and brings the Comments tab forward.
        { onSuccess: (created) => activateThread(created.id) },
      );
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

  if (typeof data === "string") {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <DocumentPreviewHeader
          label={name}
          content={data}
          showRendered={showRendered}
          onToggleRendered={() => setShowRendered((rendered) => !rendered)}
        />
        {showRendered ? (
          <div
            ref={markdownContainerRef}
            className="relative min-h-0 min-w-0 flex-1 overflow-auto"
          >
            <div ref={markdownRootRef}>
              <MarkdownDocumentPreview
                content={data}
                components={{ img: () => null }}
              />
            </div>
            <ArtifactTextAnnotations
              artifactName={name}
              rootRef={markdownRootRef}
              containerRef={markdownContainerRef}
              comments={openRootComments}
              activeThreadId={focusedThreadId}
              locateRequest={locateRequest}
              members={members}
              onActivateThread={activateThread}
              onCreate={createAnchoredComment}
              onResolutionsChange={onResolutionsChange}
            />
          </div>
        ) : (
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
            <CodeMirrorEditor content={data} filePath={name} readOnly />
          </div>
        )}
      </div>
    );
  }

  if (data && !(data instanceof Blob) && data.kind === "html") {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <GenericArtifactHeader name={name} />
        <div className="min-h-0 min-w-0 flex-1">
          <AnnotatedArtifactHtml
            html={data.html}
            name={name}
            comments={openRootComments}
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

  if (!previewUrl || !data) return <ArtifactPreviewError />;

  if (
    data instanceof Blob &&
    (isAllowedImageMimeType(data.type) || data.type === SVG_MIME_TYPE)
  ) {
    const imageActions = (
      <Button
        size="sm"
        variant={imageCommenting ? "primary" : "outline"}
        onClick={() => setImageCommenting((commenting) => !commenting)}
      >
        {imageCommenting ? <XIcon /> : <CrosshairSimpleIcon />}
        {imageCommenting ? "Cancel" : "Add comment"}
      </Button>
    );
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <GenericArtifactHeader name={name} actions={imageActions} />
        <div className="min-h-0 min-w-0 flex-1">
          <AnnotatedArtifactImage
            src={previewUrl}
            name={name}
            comments={openRootComments}
            activeThreadId={focusedThreadId}
            locateRequest={locateRequest}
            commenting={imageCommenting}
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

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <GenericArtifactHeader name={name} />
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
