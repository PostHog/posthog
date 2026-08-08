import { formatSignalReportSummaryMarkdown } from "@posthog/core/inbox/reportPresentation";
import {
  baseComponents,
  MarkdownRenderer,
} from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { reportChartAnchorId } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import type { Components } from "react-markdown";

const BaseAnchor = baseComponents.a as Extract<
  Components["a"],
  (...args: never[]) => unknown
>;

interface SignalReportSummaryMarkdownProps {
  content: string | null;
  /** Shown when `content` is null or empty after trim */
  fallback: string;
  /** List rows: clamp lines and tighter spacing. Detail: full block markdown. */
  variant: "list" | "detail";
  /** Render in italic to indicate the summary is still being written. */
  pending?: boolean;
}

// Matches the id charset the backend enforces on `chart_id` (report_charts.py).
const CHART_REF = /^chart:[a-z0-9][a-z0-9_-]*$/;

/**
 * Chart references in the summary render as in-page jumps to the chart card
 * below the prose. On list rows (where no charts render) and for ids the
 * report doesn't carry, the label degrades to plain text, matching the web
 * inbox's no-renderer fallback.
 */
const chartRefComponents: Partial<Components> = {
  a: (props) => {
    const { href, children } = props;
    if (typeof href === "string" && CHART_REF.test(href)) {
      const anchorId = reportChartAnchorId(href.slice("chart:".length));
      return (
        <a
          href={`#${anchorId}`}
          className="markdown-link"
          onClick={(event) => {
            event.preventDefault();
            document
              .getElementById(anchorId)
              ?.scrollIntoView({ behavior: "smooth", block: "center" });
          }}
        >
          {children}
        </a>
      );
    }
    return <BaseAnchor {...props} />;
  },
};

const listComponents: Partial<Components> = {
  a: (props) => {
    const { href, children } = props;
    if (typeof href === "string" && CHART_REF.test(href)) {
      return <span>{children}</span>;
    }
    return <BaseAnchor {...props} />;
  },
};

/**
 * Renders signal report summary as GFM markdown (matches backend / agent output).
 *
 * MarkdownRenderer inherits font-size from this wrapper, so setting `text-[Npx]`
 * on the outer div cascades to every paragraph / em / strong / code / link.
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
      <div
        className={`line-clamp-3 min-w-0 overflow-hidden text-pretty text-left text-[12px] text-gray-11 [&_.rt-Text]:mb-0! [&_a]:pointer-events-auto [&_li]:mb-0 [&_p]:mb-0! [&_ul]:mb-0! ${pendingClass}`}
      >
        <MarkdownRenderer
          content={listMarkdown}
          componentsOverride={listComponents}
        />
      </div>
    );
  }

  // Cap the body at ~80 chars (`ch` is sized to the column's "0" width, so this
  // tracks the 13px font without us hard-coding pixels). The wrapping `max-w` is
  // intrinsic – wider columns still get the prose, but narrower columns shrink
  // the cap with the container.
  return (
    <div
      className={`min-w-0 max-w-[80ch] text-pretty break-words text-[13px] text-gray-11 [&_*]:leading-relaxed [&_.rt-Text]:mb-2 [&_a]:pointer-events-auto [&_li]:mb-1 [&_p:last-child]:mb-0 ${pendingClass}`}
    >
      <MarkdownRenderer content={raw} componentsOverride={chartRefComponents} />
    </div>
  );
}
