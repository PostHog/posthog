// PostHog enrichment boundary data types. These are the serialized output of the
// (workspace-server) enrichment scan, consumed by the renderer to render flag/event
// annotations. They live in @posthog/shared so both the renderer (ui) and the
// enricher/ws-server can import them without crossing layer boundaries.
// @posthog/enricher re-exports these for its own consumers.

export type FlagType = "boolean" | "multivariate" | "remote_config";

export type StalenessReason =
  | "fully_rolled_out"
  | "inactive"
  | "not_in_posthog"
  | "experiment_complete";

export interface SerializedFlagOccurrence {
  method: string;
  line: number;
  startCol: number;
  endCol: number;
}

export interface SerializedFlagVariant {
  key: string;
  rolloutPercentage: number;
}

export interface SerializedFlagExperiment {
  id: number;
  name: string;
  status: "running" | "complete";
}

export interface SerializedFlag {
  flagKey: string;
  flagId: number | null;
  flagType: FlagType;
  staleness: StalenessReason | null;
  rollout: number | null;
  active: boolean;
  variants: SerializedFlagVariant[];
  occurrences: SerializedFlagOccurrence[];
  experiment: SerializedFlagExperiment | null;
}

export interface SerializedEventOccurrence {
  line: number;
  startCol: number;
  endCol: number;
  dynamic: boolean;
}

export interface SerializedEvent {
  eventName: string;
  definitionId: string | null;
  verified: boolean;
  description: string | null;
  tags: string[];
  lastSeenAt: string | null;
  volume: number | null;
  uniqueUsers: number | null;
  occurrences: SerializedEventOccurrence[];
}

export interface SerializedEnrichment {
  flags: SerializedFlag[];
  events: SerializedEvent[];
}
