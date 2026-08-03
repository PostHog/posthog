import { formatSignalReportSummaryMarkdown } from "@posthog/core/inbox/reportPresentation";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { Box } from "@radix-ui/themes";

interface SignalReportSummaryMarkdownProps {
  content: string | null;
  /** Shown when `content` is null or empty after trim */
  fallback: string;
  /** List rows: clamp lines and tighter spacing. Detail: full block markdown. */
  variant: "list" | "detail";
  /** Render in italic to indicate the summary is still being written. */
  pending?: boolean;
}

/**
 * Renders signal report summary as GFM markdown (matches backend / agent output).
 *
 * MarkdownRenderer inherits font-size from this wrapper, so setting `text-[Npx]`
 * on the outer Box cascades to every paragraph / em / strong / code / link.
 */
export function SignalReportSummaryMarkdown({
  content,
  fallback,
  variant,
  pending,
}: SignalReportSummaryMarkdownProps) {
  const rawContent = content?.trim() ? content : fallback;
  const raw = formatSignalReportSummaryMarkdown(rawContent);

  /** List rows: only the first line (before first newline); CSS still caps visual lines. */
  const listMarkdown = rawContent.split(/\r?\n/)[0] ?? "";

  const pendingClass = pending ? "italic" : "";

  if (variant === "list") {
    return (
      <Box
        className={`line-clamp-3 min-w-0 overflow-hidden text-pretty text-left text-[12px] text-gray-11 [&_.rt-Text]:mb-0! [&_a]:pointer-events-auto [&_li]:mb-0 [&_p]:mb-0! [&_ul]:mb-0! ${pendingClass}`}
      >
        <MarkdownRenderer content={listMarkdown} />
      </Box>
    );
  }

  // Cap the body at ~80 chars (`ch` is sized to the column's "0" width, so this
  // tracks the 13px font without us hard-coding pixels). The wrapping `max-w` is
  // intrinsic – wider columns still get the prose, but narrower columns shrink
  // the cap with the container.
  return (
    <Box
      className={`min-w-0 max-w-[80ch] text-pretty break-words text-[13px] text-gray-11 [&_*]:leading-relaxed [&_.rt-Text]:mb-2 [&_a]:pointer-events-auto [&_li]:mb-1 [&_p:last-child]:mb-0 ${pendingClass}`}
    >
      <MarkdownRenderer content={raw} />
    </Box>
  );
}
