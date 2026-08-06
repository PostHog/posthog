import {
  findReportChart,
  parseChartRef,
  resolveInlineChartIds,
} from "@posthog/core/inbox/reportCharts";
import { formatSignalReportSummaryMarkdown } from "@posthog/core/inbox/reportPresentation";
import type { SignalReportChart } from "@posthog/shared/types";
import {
  baseComponents,
  MarkdownRenderer,
} from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { ReportChartCard } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { useMemo } from "react";
import type { Components } from "react-markdown";
import { defaultUrlTransform } from "react-markdown";

interface SignalReportSummaryMarkdownProps {
  content: string | null;
  /** Shown when `content` is null or empty after trim */
  fallback: string;
  /** List rows: clamp lines and tighter spacing. Detail: full block markdown. */
  variant: "list" | "detail";
  /** Render in italic to indicate the summary is still being written. */
  pending?: boolean;
  /** Report id + charts let `chart:` references render as inline charts (detail only). */
  reportId?: string;
  charts?: SignalReportChart[] | null;
}

// `chart:` refs survive the transform so the components below can resolve
// them; everything else keeps react-markdown's default protocol allowlist.
function chartAwareUrlTransform(value: string): string {
  return parseChartRef(value) ? value : defaultUrlTransform(value);
}

interface HastNodeLike {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNodeLike[];
}

/**
 * Chart ids referenced by a paragraph that holds nothing else (whitespace and
 * hard breaks aside), which is the only place a block-level chart can replace
 * prose. Null when the paragraph carries anything more.
 */
function chartOnlyParagraphIds(node: unknown): string[] | null {
  const children = (node as HastNodeLike | undefined)?.children;
  if (!children) return null;
  const ids: string[] = [];
  for (const child of children) {
    if (child.type === "text") {
      if ((child.value ?? "").trim() !== "") return null;
      continue;
    }
    if (child.type === "element" && child.tagName === "br") continue;
    if (child.type === "element" && child.tagName === "a") {
      const href =
        typeof child.properties?.href === "string" ? child.properties.href : "";
      const id = parseChartRef(href);
      if (!id) return null;
      ids.push(id);
      continue;
    }
    return null;
  }
  return ids.length > 0 ? ids : null;
}

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
  reportId,
  charts,
}: SignalReportSummaryMarkdownProps) {
  const rawContent = content?.trim() ? content : fallback;
  const raw = formatSignalReportSummaryMarkdown(rawContent);

  /** List rows: only the first line (before first newline); CSS still caps visual lines. */
  const listMarkdown = rawContent.split(/\r?\n/)[0] ?? "";

  const inlineChartIds = useMemo(
    () =>
      variant === "detail" && reportId
        ? resolveInlineChartIds(rawContent, charts)
        : new Set<string>(),
    [variant, reportId, rawContent, charts],
  );

  const componentsOverride = useMemo((): Partial<Components> => {
    const BaseAnchor = baseComponents.a;
    const BaseParagraph = baseComponents.p;
    return {
      a: ({ href, children }) => {
        const chartId = parseChartRef(href);
        if (!chartId) {
          return BaseAnchor ? (
            <BaseAnchor href={href}>{children}</BaseAnchor>
          ) : (
            <a href={href}>{children}</a>
          );
        }
        // A chart reference in running prose stays text: the chart itself
        // renders below the summary (or inline when the ref stands alone),
        // so a link here would only duplicate the card's open control.
        return <span>{children}</span>;
      },
      ...(variant === "detail" && reportId
        ? {
            p: ({ node, children }) => {
              const paragraphChartIds = chartOnlyParagraphIds(node);
              // Only draw inline when every ref in this paragraph agrees with
              // the placement `ReportTrailingCharts` computed, so a chart
              // never renders twice or nowhere.
              const inlineCharts: SignalReportChart[] = [];
              for (const id of paragraphChartIds ?? []) {
                const chart = inlineChartIds.has(id)
                  ? findReportChart(charts, id)
                  : null;
                if (!chart) break;
                inlineCharts.push(chart);
              }
              if (
                paragraphChartIds &&
                inlineCharts.length === paragraphChartIds.length
              ) {
                return (
                  <div className="my-3 flex flex-col gap-3">
                    {inlineCharts.map((chart) => (
                      <ReportChartCard
                        key={chart.chart_id}
                        reportId={reportId}
                        chart={chart}
                      />
                    ))}
                  </div>
                );
              }
              return BaseParagraph ? (
                <BaseParagraph>{children}</BaseParagraph>
              ) : (
                <p>{children}</p>
              );
            },
          }
        : {}),
    };
  }, [variant, reportId, charts, inlineChartIds]);

  const pendingClass = pending ? "italic" : "";

  if (variant === "list") {
    return (
      <div
        className={`line-clamp-3 min-w-0 overflow-hidden text-pretty text-left text-[12px] text-gray-11 [&_.rt-Text]:mb-0! [&_a]:pointer-events-auto [&_li]:mb-0 [&_p]:mb-0! [&_ul]:mb-0! ${pendingClass}`}
      >
        <MarkdownRenderer
          content={listMarkdown}
          componentsOverride={componentsOverride}
          urlTransformOverride={chartAwareUrlTransform}
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
      <MarkdownRenderer
        content={raw}
        componentsOverride={componentsOverride}
        urlTransformOverride={chartAwareUrlTransform}
      />
    </div>
  );
}
