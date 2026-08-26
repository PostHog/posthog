import { CrosshairSimpleIcon, XIcon } from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type {
  CommentAnchor,
  CommentTarget,
} from "@posthog/core/comments/anchors";
import {
  Button,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { isAllowedImageMimeType } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import type {
  Dispatch,
  ReactElement,
  ReactNode,
  RefObject,
  SetStateAction,
} from "react";
import { CodeMirrorEditor } from "../../code-editor/components/CodeMirrorEditor";
import { DocumentPreviewHeader } from "../../code-editor/components/DocumentPreviewHeader";
import { MarkdownDocumentPreview } from "../../code-editor/components/MarkdownDocumentPreview";
import { AnnotatedArtifactHtml } from "./AnnotatedArtifactHtml";
import { AnnotatedArtifactImage } from "./AnnotatedArtifactImage";
import { ArtifactDocumentCommentAction } from "./ArtifactDocumentCommentAction";
import { ArtifactTextAnnotations } from "./ArtifactTextAnnotations";
import type {
  CommentLocateRequest,
  HighlightResolution,
} from "./commentViewTypes";
import type {
  ArtifactPreviewResult,
  EditableArtifactKind,
  PreviewData,
} from "./useArtifactPreviewData";

const SVG_MIME_TYPE = "image/svg+xml";

export function ArtifactPreviewError(): ReactElement {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      This artifact can’t be previewed.
    </div>
  );
}

function GenericArtifactHeader({
  name,
  versionNav,
  actions,
}: {
  name: string;
  versionNav?: ReactNode;
  actions?: ReactNode;
}): ReactElement {
  return (
    <header className="flex h-10 shrink-0 items-center justify-between gap-2 border-border border-b px-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate font-[var(--code-font-family)] text-[13px] text-muted-foreground">
          {name}
        </span>
        {versionNav}
      </div>
      {actions}
    </header>
  );
}

export function ArtifactPreviewContent({
  name,
  versionNav,
  taskId,
  commentTarget,
  canEdit,
  beginEditing,
  previewData,
  previewUrl,
  showRendered,
  setShowRendered,
  commentLoadError,
  markdownRootRef,
  markdownContainerRef,
  annotationComments,
  focusedThreadId,
  locateRequest,
  members,
  activateThread,
  createAnchoredComment,
  onResolutionsChange,
  imageCommenting,
  setImageCommenting,
  onImageError,
  editableKind,
  artifactResult,
}: {
  name: string;
  versionNav?: ReactNode;
  taskId: string;
  commentTarget: CommentTarget;
  canEdit: boolean;
  beginEditing: () => void;
  previewData: PreviewData | undefined;
  previewUrl: string | null;
  showRendered: boolean;
  setShowRendered: Dispatch<SetStateAction<boolean>>;
  commentLoadError: ReactNode;
  markdownRootRef: RefObject<HTMLDivElement | null>;
  markdownContainerRef: RefObject<HTMLDivElement | null>;
  annotationComments: ResourceComment[];
  focusedThreadId: string | null;
  locateRequest: CommentLocateRequest | null;
  members: UserBasic[];
  activateThread: (id: string) => void;
  createAnchoredComment: (
    anchor: CommentAnchor,
    content: string,
    mentions?: number[],
  ) => Promise<void>;
  onResolutionsChange: (resolutions: Map<string, HighlightResolution>) => void;
  imageCommenting: boolean;
  setImageCommenting: Dispatch<SetStateAction<boolean>>;
  onImageError: () => void;
  editableKind: EditableArtifactKind | null;
  artifactResult: ArtifactPreviewResult | undefined;
}): ReactElement {
  if (typeof previewData === "string") {
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <DocumentPreviewHeader
          label={name}
          versionNav={versionNav}
          content={previewData}
          getContent={() => previewData}
          showRendered={showRendered}
          onToggleRendered={() => setShowRendered((rendered) => !rendered)}
          canEdit={canEdit}
          onEdit={beginEditing}
          actions={
            <ArtifactDocumentCommentAction
              target={commentTarget}
              taskId={taskId}
            />
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
          versionNav={versionNav}
          content={previewData.html}
          getContent={() => previewData.html}
          showRendered
          canEdit={canEdit}
          onEdit={beginEditing}
          actions={
            <ArtifactDocumentCommentAction
              target={commentTarget}
              taskId={taskId}
            />
          }
        />
        {commentLoadError}
        <div className="min-h-0 min-w-0 flex-1">
          <AnnotatedArtifactHtml
            html={previewData.html}
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
    const imageActions = (
      <div className="flex shrink-0 items-center gap-1">
        <ArtifactDocumentCommentAction target={commentTarget} taskId={taskId} />
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="icon"
                variant={imageCommenting ? "primary" : "default"}
                aria-label={imageCommenting ? "Cancel pinning" : "Pin comment…"}
                onClick={() => setImageCommenting((commenting) => !commenting)}
              />
            }
          >
            {imageCommenting ? (
              <XIcon size={14} />
            ) : (
              <CrosshairSimpleIcon size={14} />
            )}
          </TooltipTrigger>
          <TooltipContent>
            {imageCommenting
              ? "Cancel pinning"
              : "Pin a comment to a spot on the image"}
          </TooltipContent>
        </Tooltip>
      </div>
    );
    return (
      <div className="flex h-full flex-col overflow-hidden">
        <GenericArtifactHeader
          name={name}
          versionNav={versionNav}
          actions={imageActions}
        />
        {commentLoadError}
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
            onError={onImageError}
          />
        </div>
      </div>
    );
  }

  const documentActions = (
    <ArtifactDocumentCommentAction target={commentTarget} taskId={taskId} />
  );
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {editableKind === "plain-text" && artifactResult?.source !== undefined ? (
        <DocumentPreviewHeader
          label={name}
          versionNav={versionNav}
          content={artifactResult.source}
          getContent={() => artifactResult.source ?? ""}
          showRendered
          canEdit={canEdit}
          onEdit={beginEditing}
          actions={documentActions}
        />
      ) : (
        <GenericArtifactHeader
          name={name}
          versionNav={versionNav}
          actions={documentActions}
        />
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
