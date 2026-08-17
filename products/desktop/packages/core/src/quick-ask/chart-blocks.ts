import type { QuickAskChart } from "./quick-ask";

/**
 * Transport-independent chart channel: an agent that cannot stream a query
 * artifact (a cloud task run streams plain agent text) embeds chart data in
 * its markdown as a ```posthog-chart fenced JSON block. The panel strips the
 * block from the prose and draws it with the same chart component.
 */

const CHART_FENCE = /```posthog-chart\s*\n([\s\S]*?)```/g;
/** An opening fence whose closing ``` has not streamed in yet. */
const OPEN_CHART_FENCE = /```posthog-chart\s*(?:\n[\s\S]*)?$/;

const MAX_POINTS = 120;
const MAX_SERIES = 3;

function toPoints(raw: unknown): number[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_POINTS) {
    return null;
  }
  const points = raw.map(Number);
  return points.every(Number.isFinite) ? points : null;
}

/** Validates one parsed block into a drawable chart; null when malformed. */
export function toFencedChart(raw: unknown): QuickAskChart | null {
  if (typeof raw !== "object" || raw === null) return null;
  const block = raw as {
    kind?: unknown;
    title?: unknown;
    labels?: unknown;
    series?: unknown;
  };
  const kind = block.kind === "bar" ? "bar" : "line";
  const labels = Array.isArray(block.labels)
    ? block.labels.slice(0, MAX_POINTS).map(String)
    : [];
  if (!Array.isArray(block.series)) return null;
  const series = block.series
    .slice(0, MAX_SERIES)
    .map((entry) => {
      const item = entry as { name?: unknown; points?: unknown };
      const points = toPoints(item.points);
      return points
        ? { name: typeof item.name === "string" ? item.name : "Series", points }
        : null;
    })
    .filter((entry): entry is QuickAskChart["series"][number] => entry != null);
  if (series.length === 0) return null;
  return {
    kind,
    title: typeof block.title === "string" ? block.title : "Chart",
    labels,
    series,
  };
}

export interface ExtractedCharts {
  /** The markdown with chart blocks (and any half-streamed fence) removed. */
  text: string;
  charts: QuickAskChart[];
}

export function extractChartBlocks(markdown: string): ExtractedCharts {
  const charts: QuickAskChart[] = [];
  let text = markdown.replace(CHART_FENCE, (_match, body: string) => {
    try {
      const chart = toFencedChart(JSON.parse(body));
      if (chart) charts.push(chart);
    } catch {
      // Malformed JSON: drop the block rather than show raw JSON prose.
    }
    return "";
  });
  // While streaming, hide a fence that is still growing instead of flashing
  // raw JSON until its closing backticks arrive.
  text = text.replace(OPEN_CHART_FENCE, "");
  return { text: text.trim(), charts };
}
