import { formatComments, formatInlineComments } from "./comment-formatter.js";
import {
  classifyFlagType,
  extractRollout,
  extractVariants,
} from "./flag-classification.js";
import type { ParseResult } from "./parse-result.js";
import { classifyStaleness } from "./stale-flags.js";
import type {
  EnrichedEvent,
  EnrichedFlag,
  EnrichedListItem,
  EnrichmentContext,
} from "./types.js";

export class EnrichedResult {
  private readonly parsed: ParseResult;
  private readonly context: EnrichmentContext;
  private cachedFlags: EnrichedFlag[] | null = null;
  private cachedEvents: EnrichedEvent[] | null = null;

  constructor(parsed: ParseResult, context: EnrichmentContext) {
    this.parsed = parsed;
    this.context = context;
  }

  get flags(): EnrichedFlag[] {
    if (this.cachedFlags) {
      return this.cachedFlags;
    }

    const flagMap = new Map<string, EnrichedFlag>();
    const checks = this.parsed.flagChecks;
    const experiments = this.context.experiments ?? [];

    for (const check of checks) {
      let entry = flagMap.get(check.flagKey);
      if (!entry) {
        const flag = this.context.flags?.get(check.flagKey);
        const url = this.context.flagUrls?.get(check.flagKey) ?? null;
        entry = {
          flagKey: check.flagKey,
          occurrences: [],
          flag,
          flagType: classifyFlagType(flag),
          staleness: classifyStaleness(
            check.flagKey,
            flag,
            experiments,
            this.context.stalenessOptions,
          ),
          rollout: flag ? extractRollout(flag) : null,
          variants: flag ? extractVariants(flag) : [],
          experiment: experiments.find(
            (e) => e.feature_flag_key === check.flagKey,
          ),
          url,
          evaluationStats: this.context.flagEvaluationStats?.get(check.flagKey),
          evaluationStatsError: this.context.flagEvaluationStatsError ?? false,
        };
        flagMap.set(check.flagKey, entry);
      }
      entry.occurrences.push(check);
    }

    this.cachedFlags = [...flagMap.values()];
    return this.cachedFlags;
  }

  get events(): EnrichedEvent[] {
    if (this.cachedEvents) {
      return this.cachedEvents;
    }

    const eventMap = new Map<string, EnrichedEvent>();
    const events = this.parsed.events;

    for (const event of events) {
      if (event.dynamic) {
        continue;
      }
      let entry = eventMap.get(event.name);
      if (!entry) {
        const definition = this.context.eventDefinitions?.get(event.name);
        const stats = this.context.eventStats?.get(event.name);
        entry = {
          eventName: event.name,
          occurrences: [],
          definition,
          verified: definition?.verified ?? false,
          lastSeenAt: stats?.lastSeenAt ?? definition?.last_seen_at ?? null,
          tags: definition?.tags ?? [],
          stats,
        };
        eventMap.set(event.name, entry);
      }
      entry.occurrences.push(event);
    }

    this.cachedEvents = [...eventMap.values()];
    return this.cachedEvents;
  }

  toList(): EnrichedListItem[] {
    const baseList = this.parsed.toList();
    const _experiments = this.context.experiments ?? [];

    const flagLookup = new Map<string, EnrichedFlag>();
    for (const f of this.flags) {
      flagLookup.set(f.flagKey, f);
    }

    const eventLookup = new Map<string, EnrichedEvent>();
    for (const e of this.events) {
      eventLookup.set(e.eventName, e);
    }

    return baseList.map((item) => {
      const enriched: EnrichedListItem = { ...item };

      if (item.type === "flag") {
        const flag = flagLookup.get(item.name);
        if (flag) {
          enriched.flagType = flag.flagType;
          enriched.staleness = flag.staleness;
          enriched.rollout = flag.rollout;
          enriched.active = flag.flag?.active;
          enriched.url = flag.url;
          enriched.evaluations = flag.evaluationStats?.evaluations;
          enriched.evaluationUsers = flag.evaluationStats?.uniqueUsers;
          if (flag.experiment) {
            enriched.experimentName = flag.experiment.name;
            enriched.experimentStatus = flag.experiment.end_date
              ? "complete"
              : "running";
          }
        }
      } else if (item.type === "event") {
        const event = eventLookup.get(item.name);
        if (event) {
          enriched.verified = event.verified;
          enriched.description = event.definition?.description ?? null;
          enriched.lastSeenAt = event.lastSeenAt;
          enriched.tags = event.tags;
          enriched.volume = event.stats?.volume;
          enriched.uniqueUsers = event.stats?.uniqueUsers;
        }
      }

      return enriched;
    });
  }

  toComments(): string {
    const flagLookup = new Map<string, EnrichedFlag>();
    for (const f of this.flags) {
      flagLookup.set(f.flagKey, f);
    }

    const eventLookup = new Map<string, EnrichedEvent>();
    for (const e of this.events) {
      eventLookup.set(e.eventName, e);
    }

    return formatComments(
      this.parsed.source,
      this.parsed.languageId,
      this.toList(),
      flagLookup,
      eventLookup,
    );
  }

  toInlineComments(): string {
    const flagLookup = new Map<string, EnrichedFlag>();
    for (const f of this.flags) {
      flagLookup.set(f.flagKey, f);
    }

    const eventLookup = new Map<string, EnrichedEvent>();
    for (const e of this.events) {
      eventLookup.set(e.eventName, e);
    }

    return formatInlineComments(
      this.parsed.source,
      this.parsed.languageId,
      this.toList(),
      flagLookup,
      eventLookup,
    );
  }
}
