import { ChatCircleTextIcon } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { parseCommentContextBody } from "./commentContextBody";
import { useLocalImage } from "./useLocalImage";

export function CommentContextPreview({
  label,
  body,
  imagePath,
}: {
  label: string;
  body: string;
  imagePath?: string;
}) {
  const image = useLocalImage(imagePath);
  const { quote, snippet } = parseCommentContextBody(body);
  return (
    <div className="flex w-80 min-w-0 max-w-[80vw] flex-col gap-2 py-0.5 text-left text-xs">
      {image ? (
        <img
          src={image}
          alt={`Screenshot of ${label}`}
          className="block max-h-56 w-full rounded-md object-contain ring-1 ring-current/15"
        />
      ) : null}
      <div className="flex min-w-0 items-center gap-1.5 font-medium">
        <ChatCircleTextIcon size={13} className="shrink-0 opacity-70" />
        <span className="min-w-0 truncate">{label}</span>
      </div>
      {!image && quote && (
        <blockquote className="line-clamp-4 whitespace-pre-wrap border-current/30 border-l-2 pl-2 opacity-90">
          {quote}
        </blockquote>
      )}
      {!image && !quote && snippet && (
        <pre
          className={cn(
            "max-h-24 overflow-hidden whitespace-pre-wrap break-all rounded bg-current/10 px-2 py-1.5 font-mono text-[11px] leading-relaxed",
          )}
        >
          {snippet}
        </pre>
      )}
    </div>
  );
}
