import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { RegionCommentAnchor } from "@posthog/core/comments/anchors";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { ZoomableImage } from "@posthog/ui/primitives/SafeImagePreview";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  type CommentLocateRequest,
  readCommentContext,
} from "./commentViewTypes";

/** Whose pin it is, for the marker's label. */
function authorName(comment: ResourceComment): string {
  const user = comment.created_by;
  if (!user) return "Deleted user";
  return (
    [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email
  );
}

function ImageCommentCreationLayer({
  name,
  members,
  onCreate,
  onCancel,
}: {
  name: string;
  members: UserBasic[];
  onCreate: (
    anchor: RegionCommentAnchor,
    content: string,
    mentions?: number[],
  ) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [pendingAnchor, setPendingAnchor] =
    useState<RegionCommentAnchor | null>(null);
  const [selection, setSelection] = useState<EditorSelection | null>(null);

  return (
    <>
      <button
        type="button"
        aria-label="Place image comment"
        className="absolute inset-0 z-20 cursor-crosshair"
        onClick={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const keyboard = event.detail === 0;
          const clientX = keyboard ? box.left + box.width / 2 : event.clientX;
          const clientY = keyboard ? box.top + box.height / 2 : event.clientY;
          const x = (clientX - box.left) / box.width;
          const y = (clientY - box.top) / box.height;
          const size = 0.035;
          setPendingAnchor({
            kind: "region",
            x: Math.max(0, Math.min(1 - size, x - size / 2)),
            y: Math.max(0, Math.min(1 - size, y - size / 2)),
            width: size,
            height: size,
          });
          setSelection({
            text: "Image region",
            fromLine: 1,
            toLine: 1,
            // Point anchor at the click: the composer opens next to it.
            anchor: { top: clientY, endX: clientX, bottom: clientY },
          });
        }}
      />
      <SelectionCommentOverlay
        selection={selection}
        open={!!selection && !!pendingAnchor}
        filePath={name}
        actionLabel="Add image comment"
        placeholder="Add a comment about this part of the image..."
        initiallyExpanded
        members={members}
        onDismiss={onCancel}
        onSubmit={async (_start, _end, content, mentions) => {
          if (pendingAnchor) await onCreate(pendingAnchor, content, mentions);
        }}
      />
    </>
  );
}

export function AnnotatedArtifactImage({
  src,
  name,
  comments,
  activeThreadId,
  locateRequest,
  commenting,
  members,
  onCommentingChange,
  onActivateThread,
  onCreate,
  onError,
}: {
  src: string;
  name: string;
  comments: ResourceComment[];
  activeThreadId: string | null;
  locateRequest: CommentLocateRequest | null;
  commenting: boolean;
  members: UserBasic[];
  onCommentingChange: (commenting: boolean) => void;
  onActivateThread: (id: string) => void;
  onCreate: (
    anchor: RegionCommentAnchor,
    content: string,
    mentions?: number[],
  ) => void | Promise<void>;
  onError: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!locateRequest) return;
    rootRef.current
      ?.querySelector<HTMLElement>(
        `[data-image-comment-id="${CSS.escape(locateRequest.id)}"]`,
      )
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [locateRequest]);

  const regionComments = useMemo(
    () =>
      comments.flatMap((comment) => {
        const context = readCommentContext(comment);
        return context?.anchor.kind === "region"
          ? [{ comment, anchor: context.anchor }]
          : [];
      }),
    [comments],
  );

  // Takes the zoom scale so a pin keeps its on-screen size: the overlay is
  // inside the transformed content, so it would otherwise grow with the image.
  const overlay = (scale: number) => (
    <>
      {commenting && (
        <ImageCommentCreationLayer
          name={name}
          members={members}
          onCreate={onCreate}
          onCancel={() => onCommentingChange(false)}
        />
      )}
      <div className="pointer-events-none absolute inset-0 z-30">
        {regionComments.map(({ comment, anchor }) => (
          // A marker, not a quill Button: that one nudges itself down on press
          // and keeps a dark focus ring afterwards, both of which read as a
          // glitch on something pinned to a picture. Squaring one corner of a
          // circle makes the teardrop, and that corner is the anchor point, so
          // the pin hangs off the spot rather than covering it.
          //
          // Shell and ring are opposite ends of the grey scale, so the pin
          // carries its own contrast onto artwork of any colour, and both steps
          // are opaque — an avatar with transparency in it (plenty of Gravatars
          // have) must not let the picture bleed through.
          <button
            key={comment.id}
            type="button"
            aria-label={`Open comment from ${authorName(comment)}`}
            title={comment.content ?? "Comment"}
            data-image-comment-id={comment.id}
            className={`pointer-events-auto absolute flex size-8 items-center justify-center rounded-full rounded-bl-none p-1 ring-1 transition-all focus-visible:outline-(--gray-1) focus-visible:outline-2 focus-visible:outline-offset-1 ${
              comment.id === activeThreadId
                ? "bg-(--blue-12) ring-(--blue-10)"
                : "bg-(--gray-12) ring-(--gray-10)"
            }`}
            style={{
              left: `${anchor.x * 100}%`,
              top: `${(anchor.y + anchor.height) * 100}%`,
              transform: `translate(0, -100%) scale(${1 / scale})`,
              transformOrigin: "bottom left",
            }}
            onClick={() => onActivateThread(comment.id)}
          >
            <UserAvatar
              user={comment.created_by}
              size="sm"
              className="rounded-full bg-(--gray-1)"
            />
          </button>
        ))}
      </div>
    </>
  );

  return (
    <div
      ref={rootRef}
      className="relative size-full overflow-hidden bg-(--gray-2) p-4"
    >
      <ZoomableImage
        src={src}
        alt={name}
        controls
        overlay={overlay}
        className="size-full"
        onError={onError}
      />
    </div>
  );
}
