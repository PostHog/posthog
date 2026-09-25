import { ChatCircleTextIcon } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import { inlineCodeRuns, parseCommentContextBody } from "./commentContextBody";

export function CommentContextPreview({
  label,
  body,
  size = "compact",
}: {
  label: string;
  body: string;
  size?: "compact" | "full";
}) {
  const { fields, quote, snippet } = parseCommentContextBody(body);
  const compact = size === "compact";
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-2 text-left text-xs",
        compact ? "w-80 max-w-[80vw] py-0.5" : "w-full",
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5 font-medium">
        <ChatCircleTextIcon size={13} className="shrink-0 opacity-70" />
        <span className="min-w-0 truncate">{label}</span>
      </div>
      {fields.length > 0 && (
        <dl className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
          {fields.map((field) => (
            <div key={field.key} className="contents">
              <dt className="opacity-60">{field.key}</dt>
              <dd
                className={cn("min-w-0", compact ? "truncate" : "break-words")}
              >
                {inlineCodeRuns(field.value).map((run) =>
                  run.code ? (
                    <code key={run.key} className="font-mono text-[11px]">
                      {run.text}
                    </code>
                  ) : (
                    <span key={run.key}>{run.text}</span>
                  ),
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {quote && (
        <blockquote
          className={cn(
            "whitespace-pre-wrap border-current/30 border-l-2 pl-2 opacity-90",
            compact && "line-clamp-4",
          )}
        >
          {quote}
        </blockquote>
      )}
      {snippet && (
        <pre
          className={cn(
            "overflow-hidden whitespace-pre-wrap break-all rounded bg-current/10 px-2 py-1.5 font-mono text-[11px] leading-relaxed",
            compact && "max-h-24",
          )}
        >
          {snippet}
        </pre>
      )}
    </div>
  );
}
