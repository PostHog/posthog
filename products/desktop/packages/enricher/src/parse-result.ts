import { EnrichedResult } from "./enriched-result.js";
import { warn } from "./log.js";
import { PostHogApi } from "./posthog-api.js";
import type {
  CapturedEvent,
  EnricherApiConfig,
  EventStats,
  FlagAssignment,
  FlagCheck,
  FlagEvaluationStats,
  FunctionInfo,
  ListItem,
  PostHogCall,
  PostHogInitCall,
  VariantBranch,
} from "./types.js";

const CAPTURE_METHODS = new Set(["capture", "Enqueue"]);

export class ParseResult {
  readonly source: string;
  readonly languageId: string;
  readonly calls: readonly PostHogCall[];
  readonly initCalls: readonly PostHogInitCall[];
  readonly flagAssignments: readonly FlagAssignment[];
  readonly variantBranches: readonly VariantBranch[];
  readonly functions: readonly FunctionInfo[];

  constructor(
    source: string,
    languageId: string,
    calls: PostHogCall[],
    initCalls: PostHogInitCall[],
    flagAssignments: FlagAssignment[],
    variantBranches: VariantBranch[],
    functions: FunctionInfo[],
  ) {
    this.source = source;
    this.languageId = languageId;
    this.calls = calls;
    this.initCalls = initCalls;
    this.flagAssignments = flagAssignments;
    this.variantBranches = variantBranches;
    this.functions = functions;
  }

  get events(): CapturedEvent[] {
    return this.calls
      .filter((c) => CAPTURE_METHODS.has(c.method))
      .map((c) => ({
        name: c.key,
        line: c.line,
        keyStartCol: c.keyStartCol,
        keyEndCol: c.keyEndCol,
        dynamic: c.dynamic ?? false,
        viaWrapper: c.viaWrapper,
        inJsx: c.inJsx,
      }));
  }

  get flagChecks(): FlagCheck[] {
    return this.calls
      .filter((c) => !CAPTURE_METHODS.has(c.method))
      .map((c) => ({
        method: c.method,
        flagKey: c.key,
        line: c.line,
        keyStartCol: c.keyStartCol,
        keyEndCol: c.keyEndCol,
        viaWrapper: c.viaWrapper,
        inJsx: c.inJsx,
      }));
  }

  get flagKeys(): string[] {
    return [...new Set(this.flagChecks.map((c) => c.flagKey))];
  }

  get eventNames(): string[] {
    return [
      ...new Set(this.events.filter((e) => !e.dynamic).map((e) => e.name)),
    ];
  }

  toList(): ListItem[] {
    const items: ListItem[] = [];

    for (const init of this.initCalls) {
      items.push({
        type: "init",
        line: init.tokenLine,
        name: init.token,
        method: "init",
      });
    }

    for (const call of this.calls) {
      const isEvent = CAPTURE_METHODS.has(call.method);
      items.push({
        type: isEvent ? "event" : "flag",
        line: call.line,
        name: call.key,
        method: call.method,
        detail: call.dynamic ? "dynamic event name" : undefined,
        viaWrapper: call.viaWrapper,
        inJsx: call.inJsx,
      });
    }

    return items.sort((a, b) => a.line - b.line);
  }

  async enrichFromApi(config: EnricherApiConfig): Promise<EnrichedResult> {
    const api = new PostHogApi(config);
    const flagKeys = this.flagKeys;
    const eventNames = this.eventNames;

    const settled = await Promise.allSettled([
      flagKeys.length > 0 ? api.getFeatureFlags() : Promise.resolve([]),
      flagKeys.length > 0 ? api.getExperiments() : Promise.resolve([]),
      eventNames.length > 0
        ? api.getEventDefinitions(eventNames)
        : Promise.resolve([]),
      eventNames.length > 0
        ? api.getEventStats(eventNames)
        : Promise.resolve(new Map()),
      flagKeys.length > 0
        ? api.getFlagEvaluationStats(flagKeys, 7)
        : Promise.resolve(new Map()),
    ]);

    const [
      flagsResult,
      experimentsResult,
      eventDefsResult,
      eventStatsResult,
      flagEvalStatsResult,
    ] = settled;

    const labels = [
      "getFeatureFlags",
      "getExperiments",
      "getEventDefinitions",
      "getEventStats",
      "getFlagEvaluationStats",
    ];
    settled.forEach((r, i) => {
      if (r.status === "rejected") {
        warn(`enricher: ${labels[i]} failed`, r.reason);
      }
    });

    const allFlags =
      flagsResult.status === "fulfilled" ? flagsResult.value : [];
    const allExperiments =
      experimentsResult.status === "fulfilled" ? experimentsResult.value : [];
    const allEventDefs =
      eventDefsResult.status === "fulfilled" ? eventDefsResult.value : [];
    const eventStats =
      eventStatsResult.status === "fulfilled"
        ? eventStatsResult.value
        : new Map<string, EventStats>();
    const flagEvaluationStats =
      flagEvalStatsResult.status === "fulfilled"
        ? flagEvalStatsResult.value
        : new Map<string, FlagEvaluationStats>();
    const flagEvaluationStatsError = flagEvalStatsResult.status === "rejected";

    const flagKeySet = new Set(flagKeys);
    const flags = new Map(
      allFlags.filter((f) => flagKeySet.has(f.key)).map((f) => [f.key, f]),
    );

    const experiments = allExperiments.filter((e) =>
      flagKeySet.has(e.feature_flag_key),
    );

    const eventDefinitions = new Map(
      allEventDefs
        .filter((d) => eventNames.includes(d.name))
        .map((d) => [d.name, d]),
    );

    const host = config.host.replace(/\/$/, "");
    const flagUrls = new Map<string, string>();
    for (const [key, flag] of flags) {
      flagUrls.set(
        key,
        `${host}/project/${config.projectId}/feature_flags/${flag.id}`,
      );
    }

    return new EnrichedResult(this, {
      flags,
      experiments,
      eventDefinitions,
      eventStats,
      flagEvaluationStats,
      flagEvaluationStatsError,
      flagUrls,
    });
  }
}
