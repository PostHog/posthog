import type {
  SerializedEnrichment,
  SerializedEvent,
  SerializedFlag,
} from "@posthog/shared";

export type EnrichmentPopoverEntry =
  | { kind: "flag"; data: SerializedFlag }
  | { kind: "event"; data: SerializedEvent };

export interface EnrichmentOccurrence {
  line: number;
  startCol: number;
  endCol: number;
  entry: EnrichmentPopoverEntry;
  summary: string;
}

export function buildEnrichmentOccurrences(
  data: SerializedEnrichment | null,
): EnrichmentOccurrence[] {
  if (!data) return [];
  const out: EnrichmentOccurrence[] = [];

  for (const flag of data.flags) {
    for (const occ of flag.occurrences) {
      out.push({
        line: occ.line + 1,
        startCol: occ.startCol,
        endCol: occ.endCol,
        entry: { kind: "flag", data: flag },
        summary: `Flag: ${flag.flagKey}`,
      });
    }
  }
  for (const event of data.events) {
    for (const occ of event.occurrences) {
      out.push({
        line: occ.line + 1,
        startCol: occ.startCol,
        endCol: occ.endCol,
        entry: { kind: "event", data: event },
        summary: `Event: ${event.eventName}`,
      });
    }
  }

  out.sort((a, b) =>
    a.line !== b.line ? a.line - b.line : a.startCol - b.startCol,
  );
  return out;
}
