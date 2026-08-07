import type {
  SerializedEnrichment,
  SerializedEvent,
  SerializedFlag,
} from "@posthog/shared";
import type { EnrichedResult } from "./enriched-result.js";

export type {
  SerializedEnrichment,
  SerializedEvent,
  SerializedEventOccurrence,
  SerializedFlag,
  SerializedFlagExperiment,
  SerializedFlagOccurrence,
  SerializedFlagVariant,
} from "@posthog/shared";

export function toSerializable(enriched: EnrichedResult): SerializedEnrichment {
  const flags: SerializedFlag[] = enriched.flags.map((f) => ({
    flagKey: f.flagKey,
    flagId: f.flag?.id ?? null,
    flagType: f.flagType,
    staleness: f.staleness,
    rollout: f.rollout,
    active: f.flag?.active ?? false,
    variants: f.variants.map((v) => ({
      key: v.key,
      rolloutPercentage: v.rollout_percentage,
    })),
    occurrences: f.occurrences.map((o) => ({
      method: o.method,
      line: o.line,
      startCol: o.keyStartCol,
      endCol: o.keyEndCol,
    })),
    experiment: f.experiment
      ? {
          id: f.experiment.id,
          name: f.experiment.name,
          status: f.experiment.end_date ? "complete" : "running",
        }
      : null,
  }));

  const events: SerializedEvent[] = enriched.events.map((e) => ({
    eventName: e.eventName,
    definitionId: e.definition?.id ?? null,
    verified: e.verified,
    description: e.definition?.description ?? null,
    tags: e.tags,
    lastSeenAt: e.lastSeenAt,
    volume: e.stats?.volume ?? null,
    uniqueUsers: e.stats?.uniqueUsers ?? null,
    occurrences: e.occurrences.map((o) => ({
      line: o.line,
      startCol: o.keyStartCol,
      endCol: o.keyEndCol,
      dynamic: o.dynamic,
    })),
  }));

  return { flags, events };
}
