import {
  CrosshairSimpleIcon,
  FloppyDiskIcon,
  PencilSimpleIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  ArtifactVersionConflictError,
  type ResourceComment,
} from "@posthog/api-client/posthog-client";
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
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Spinner,
} from "@posthog/quill";
import { isAllowedImageMimeType } from "@posthog/shared";
import type { TaskArtifactVersion } from "@posthog/shared/domain-types";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { toast } from "@posthog/ui/primitives/toast";
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
import { ArtifactDocumentCommentAction } from "./ArtifactDocumentCommentAction";
import { ArtifactTextAnnotations } from "./ArtifactTextAnnotations";
import { artifactPreviewBlob } from "./artifactPreviewDocument";
import {
  buildCommentThreads,
  type CommentLocateRequest,
  type HighlightResolution,
} from "./commentViewTypes";
import { useArtifactVersions } from "./useArtifactVersions";
import { useCommentsQuery, useCreateComment } from "./useComments";
import { useSaveArtifactVersion } from "./useSaveArtifactVersion";

const MARKDOWN_EXTENSIONS = new Set(["md", "mdx", "markdown"]);
const HTML_EXTENSIONS = new Set(["html", "htm"]);
const TEXT_EXTENSIONS = new Set([
  "c",
  "cc",
  "conf",
  "cpp",
  "css",
  "csv",
  "go",
  "h",
  "ini",
  "java",
  "js",
  "json",
  "jsx",
  "log",
  "py",
  "rb",
  "rs",
  "sh",
  "sql",
  "toml",
  "ts",
  "tsv",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
]);
const TEXT_APPLICATION_TYPES = new Set([
  "application/javascript",
  "application/json",
  "application/sql",
  "application/toml",
  "application/xml",
  "application/x-yaml",
  "application/yaml",
]);
/** SVG is excluded from the shared image allowlist because its scripts can run
 *  when it comes from a data URL. An <img> renders SVG in a secure static mode
 *  that never runs scripts, so the zoom-and-annotate surface is safe for it. */
const SVG_MIME_TYPE = "image/svg+xml";
const EMPTY_COMMENTS: ResourceComment[] = [];

type TextFormat = "html" | "markdown" | "plain";
type TextPreview = { kind: "text"; content: string; format: TextFormat };
type LegacyHtmlPreview = { kind: "html"; html: string };
type PreviewData = string | Blob | TextPreview | LegacyHtmlPreview;

function extension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

function textFormat(filename: string): TextFormat {
  const fileExtension = extension(filename);
  if (MARKDOWN_EXTENSIONS.has(fileExtension)) return "markdown";
  if (HTML_EXTENSIONS.has(fileExtension)) return "html";
  return "plain";
}

function isTextArtifact(filename: string, contentType: string): boolean {
  const normalizedContentType =
    contentType.split(";", 1)[0]?.trim().toLowerCase() ?? "";
  const fileExtension = extension(filename);
  return (
    normalizedContentType.startsWith("text/") ||
    TEXT_APPLICATION_TYPES.has(normalizedContentType) ||
    MARKDOWN_EXTENSIONS.has(fileExtension) ||
    HTML_EXTENSIONS.has(fileExtension) ||
    TEXT_EXTENSIONS.has(fileExtension)
  );
}

function ArtifactPreviewError() {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      This artifact can’t be previewed.
    </div>
  );
}

function ArtifactVersionSelect({
  versions,
  value,
  disabled,
  onChange,
}: {
  versions: TaskArtifactVersion[];
  value: string | null;
  disabled: boolean;
  onChange: (versionId: string) => void;
}) {
  if (versions.length === 0 || !value) return null;
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(nextValue) => nextValue && onChange(nextValue)}
    >
      <SelectTrigger size="sm" aria-label="Artifact version">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {versions.map((version, index) => (
          <SelectItem key={version.id} value={version.id}>
            Version {version.version}
            {index === 0 ? " (current)" : ""}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
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
      <div className="flex items-center gap-1">{actions}</div>
    </header>
  );
}

/** The artifact is the whole pane: its threads are listed in the task's
 *  Comments tab, and this only renders and locates their anchors. */
export function ArtifactPreview({
  taskId,
  runId,
  artifactId,
  runArtifactId = artifactId,
  initialVersionId = null,
  initialVersion = null,
  editable = false,
  contentType = "application/octet-stream",
  name,
}: {
  taskId: string;
  runId: string;
  artifactId: string;
  runArtifactId?: string;
  initialVersionId?: string | null;
  initialVersion?: number | null;
  editable?: boolean;
  contentType?: string;
  name: string;
}) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const versionsQuery = useArtifactVersions(
    taskId,
    artifactId,
    initialVersionId !== null,
  );
  const saveVersion = useSaveArtifactVersion(taskId, artifactId);
  const updateTabMetadata = usePanelLayoutStore(
    (state) => state.updateTabMetadata,
  );
  const versions = versionsQuery.data ?? [];
  const currentVersion = versions[0] ?? null;
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    initialVersionId,
  );
  const selectedVersion = selectedVersionId
    ? (versions.find((version) => version.id === selectedVersionId) ?? null)
    : currentVersion;
  const displayedRunId = selectedVersion?.run_id ?? runId;
  const displayedRunArtifactId =
    selectedVersion?.run_artifact_id ?? runArtifactId;
  const displayedVersionId =
    selectedVersion?.id ?? initialVersionId ?? currentVersion?.id ?? null;
  const displayedVersionNumber =
    selectedVersion?.version ??
    initialVersion ??
    currentVersion?.version ??
    null;
  const displayedContentType = selectedVersion?.content_type || contentType;
  const displayedEditable = selectedVersion
    ? (selectedVersion.size ?? Number.POSITIVE_INFINITY) <= 500_000 &&
      isTextArtifact(name, displayedContentType)
    : editable;
  const expectedVersionId = currentVersion?.id ?? initialVersionId;
  const saveRunId = currentVersion?.run_id ?? runId;
  const [showRendered, setShowRendered] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const draftRef = useRef("");
  const markdownRootRef = useRef<HTMLDivElement>(null);
  const markdownContainerRef = useRef<HTMLDivElement>(null);
  const [imageError, setImageError] = useState(false);
  const [imageCommenting, setImageCommenting] = useState(false);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const commentTarget = useMemo<CommentTarget>(
    () => ({ scope: "task_artifact", itemId: artifactId }),
    [artifactId],
  );
  const commentsQuery = useCommentsQuery(commentTarget, taskId);
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
    queryKey: [
      "artifactPreview",
      authIdentity,
      taskId,
      displayedRunId,
      displayedRunArtifactId,
    ],
    queryFn: async () => {
      const url = await sessionService.getCloudAttachmentPreviewUrl(
        taskId,
        displayedRunId,
        displayedRunArtifactId,
      );
      if (!url) throw new Error("Artifact is unavailable");
      const response = await fetch(url);
      if (!response.ok) throw new Error("Artifact preview failed");
      const blob = await response.blob();
      if (isTextArtifact(name, blob.type || displayedContentType)) {
        const content = new TextDecoder("utf-8", { fatal: true }).decode(
          await blob.arrayBuffer(),
        );
        if (content.includes("\0")) throw new Error("Artifact is not text");
        return { kind: "text", content, format: textFormat(name) };
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

  useEffect(() => {
    if (
      selectedVersionId &&
      versions.length > 0 &&
      !versions.some((version) => version.id === selectedVersionId)
    ) {
      setSelectedVersionId(null);
    }
  }, [selectedVersionId, versions]);

  useEffect(() => {
    const tabId = `artifact-${artifactId}`;
    updateTabMetadata(taskId, tabId, { hasUnsavedChanges: isDirty });
    return () => updateTabMetadata(taskId, tabId, { hasUnsavedChanges: false });
  }, [artifactId, isDirty, taskId, updateTabMetadata]);

  useEffect(() => {
    if (!isDirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [isDirty]);

  const previousDisplayedVersionId = useRef(displayedVersionId);
  useEffect(() => {
    if (previousDisplayedVersionId.current === displayedVersionId) return;
    previousDisplayedVersionId.current = displayedVersionId;
    setIsEditing(false);
    setIsDirty(false);
    setImageError(false);
  }, [displayedVersionId]);

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
        context: {
          anchor,
          ...(displayedVersionId
            ? { artifactVersionId: displayedVersionId }
            : {}),
        },
        mentions,
      });
      activateThread(created.id);
    },
    [createComment, activateThread, displayedVersionId],
  );

  const textPreview: TextPreview | null =
    typeof data === "string"
      ? { kind: "text", content: data, format: "markdown" }
      : data && !(data instanceof Blob) && data.kind === "html"
        ? { kind: "text", content: data.html, format: "html" }
        : data && !(data instanceof Blob) && data.kind === "text"
          ? data
          : null;

  const startEditing = useCallback(() => {
    if (!textPreview) return;
    draftRef.current = textPreview.content;
    setIsDirty(false);
    setIsEditing(true);
    setShowRendered(false);
  }, [textPreview]);

  const save = useCallback(async () => {
    if (!expectedVersionId || !textPreview || !isDirty) return;
    try {
      await saveVersion.mutateAsync({
        runId: saveRunId,
        expectedVersionId,
        name,
        contentType: displayedContentType,
        content: draftRef.current,
      });
      setSelectedVersionId(null);
      setIsEditing(false);
      setIsDirty(false);
      toast.success("Saved artifact version");
    } catch (error) {
      if (error instanceof ArtifactVersionConflictError) {
        toast.error("A newer version is available", {
          description:
            "Your draft is still open. Load the latest version before saving again.",
        });
        return;
      }
      toast.error("Couldn't save artifact", {
        description: "Try again.",
      });
    }
  }, [
    displayedContentType,
    expectedVersionId,
    isDirty,
    name,
    saveRunId,
    saveVersion,
    textPreview,
  ]);

  useEffect(() => {
    if (!isEditing) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        !(event.metaKey || event.ctrlKey) ||
        event.key.toLowerCase() !== "s"
      ) {
        return;
      }
      event.preventDefault();
      void save();
    };
    document.addEventListener("keydown", onKeyDown, { capture: true });
    return () =>
      document.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [isEditing, save]);

  const versionSelect = (
    <ArtifactVersionSelect
      versions={versions}
      value={displayedVersionId}
      disabled={isEditing}
      onChange={(versionId) =>
        setSelectedVersionId(
          versionId === currentVersion?.id ? null : versionId,
        )
      }
    />
  );
  const commentAction = (
    <ArtifactDocumentCommentAction
      target={commentTarget}
      taskId={taskId}
      artifactVersionId={displayedVersionId}
    />
  );
  const editActions =
    textPreview && displayedEditable && expectedVersionId ? (
      isEditing ? (
        <>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setIsEditing(false);
              setIsDirty(false);
            }}
          >
            <XIcon />
            Cancel
          </Button>
          <Button
            size="sm"
            variant="primary"
            loading={saveVersion.isPending}
            disabled={!isDirty}
            onClick={() => void save()}
          >
            <FloppyDiskIcon />
            Save
          </Button>
        </>
      ) : (
        <Button size="sm" variant="outline" onClick={startEditing}>
          <PencilSimpleIcon />
          Edit
        </Button>
      )
    ) : null;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (isError || imageError) return <ArtifactPreviewError />;

  if (textPreview) {
    const canRender = textPreview.format !== "plain";
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <DocumentPreviewHeader
          label={
            displayedVersionNumber
              ? `${name} · Version ${displayedVersionNumber}`
              : name
          }
          content={isEditing ? draftRef.current : textPreview.content}
          showRendered={showRendered && !isEditing}
          canToggleRendered={canRender && !isEditing}
          onToggleRendered={() => setShowRendered((rendered) => !rendered)}
          actions={
            <>
              {versionSelect}
              {!isEditing && commentAction}
              {editActions}
            </>
          }
        />
        {isEditing ? (
          <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
            <CodeMirrorEditor
              key={`edit:${displayedVersionId}`}
              content={textPreview.content}
              filePath={name}
              onContentChange={(content) => {
                draftRef.current = content;
                setIsDirty(content !== textPreview.content);
              }}
            />
          </div>
        ) : showRendered && textPreview.format === "markdown" ? (
          <div
            ref={markdownContainerRef}
            className="relative min-h-0 min-w-0 flex-1 overflow-auto"
          >
            <div ref={markdownRootRef}>
              <MarkdownDocumentPreview
                content={textPreview.content}
                components={{ img: () => null }}
              />
            </div>
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
          </div>
        ) : showRendered && textPreview.format === "html" ? (
          <div className="min-h-0 min-w-0 flex-1">
            <AnnotatedArtifactHtml
              html={textPreview.content}
              name={name}
              comments={annotationComments}
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
            <CodeMirrorEditor
              key={`source:${displayedVersionId}`}
              content={textPreview.content}
              filePath={name}
              readOnly
            />
          </div>
        )}
      </div>
    );
  }

  if (!previewUrl || !data) return <ArtifactPreviewError />;

  if (
    data instanceof Blob &&
    (isAllowedImageMimeType(data.type) || data.type === SVG_MIME_TYPE)
  ) {
    const imageActions = (
      <>
        {versionSelect}
        {commentAction}
        <Button
          size="sm"
          variant={imageCommenting ? "primary" : "outline"}
          onClick={() => setImageCommenting((commenting) => !commenting)}
        >
          {imageCommenting ? <XIcon /> : <CrosshairSimpleIcon />}
          {imageCommenting ? "Cancel" : "Pin comment…"}
        </Button>
      </>
    );
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <GenericArtifactHeader name={name} actions={imageActions} />
        <div className="min-h-0 min-w-0 flex-1">
          <AnnotatedArtifactImage
            src={previewUrl}
            name={name}
            comments={annotationComments}
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
      <GenericArtifactHeader
        name={name}
        actions={
          <>
            {versionSelect}
            {commentAction}
          </>
        }
      />
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
