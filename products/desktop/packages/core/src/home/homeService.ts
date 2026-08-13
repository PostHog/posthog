import {
  PROJECT_API_CLIENT,
  type ProjectApiClient,
} from "@posthog/core/canvas/projectApiClient";
import { inject, injectable } from "inversify";
import type {
  HomeExperiment,
  HomeExperimentStage,
  HomeFeatureFlag,
  HomeWork,
  HomeWorkInput,
} from "./homeSchemas";

// One page each, sorted newest-first by the API. Home shows a handful; the rest
// of the page is headroom for the filtering below (a flag that already drives an
// experiment drops out, and so does one whose space already exists).
const FLAG_PAGE_SIZE = 50;
const EXPERIMENT_PAGE_SIZE = 50;

interface ApiUser {
  id?: number;
  first_name?: string;
  last_name?: string;
  email?: string;
}

interface ApiFeatureFlag {
  id: number;
  key: string;
  name?: string | null;
  active?: boolean;
  filters?: { groups?: { rollout_percentage?: number | null }[] } | null;
  experiment_set?: unknown[] | null;
  created_by?: ApiUser | null;
  created_at?: string | null;
}

interface ApiExperiment {
  id: number;
  name: string;
  description?: string | null;
  feature_flag_key?: string | null;
  status?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  parameters?: { feature_flag_variants?: { key?: string }[] } | null;
  created_by?: ApiUser | null;
  created_at?: string | null;
}

function displayName(user: ApiUser | null | undefined): string | null {
  if (!user) return null;
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return name || user.email || null;
}

function epoch(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * The experiment's API status, in Home's vocabulary. `exposure_frozen` reads as
 * running because the experiment is still collecting metrics; an unrecognized
 * status is treated as a draft rather than claimed to be live.
 */
function toStage(status: string | null | undefined): HomeExperimentStage {
  switch (status) {
    case "running":
    case "exposure_frozen":
      return "running";
    case "paused":
      return "paused";
    case "stopped":
      return "concluded";
    default:
      return "draft";
  }
}

/** The flag's release rollout, where it has a single release condition. */
function rolloutPercentage(flag: ApiFeatureFlag): number | null {
  const groups = flag.filters?.groups ?? [];
  if (groups.length !== 1) return null;
  const percentage = groups[0]?.rollout_percentage;
  return typeof percentage === "number" ? percentage : null;
}

/**
 * Reads back the work a person already has in PostHog — the feature flags and
 * experiments Home opens on. Nothing here writes.
 *
 * A group that fails to load comes back in `unavailable` instead of failing the
 * whole call: a Home missing one section still beats a Home that shows nothing
 * because one scope is absent.
 */
@injectable()
export class HomeService {
  constructor(
    @inject(PROJECT_API_CLIENT)
    private readonly api: ProjectApiClient,
  ) {}

  async work(input: HomeWorkInput): Promise<HomeWork> {
    const viewerId = input.viewerId ?? null;
    const [flags, experiments] = await Promise.all([
      this.featureFlags(viewerId),
      this.experiments(viewerId),
    ]);

    const unavailable: HomeWork["unavailable"] = [];
    if (flags === null) unavailable.push("featureFlags");
    if (experiments === null) unavailable.push("experiments");

    return {
      featureFlags: (flags ?? []).slice(0, input.limit),
      experiments: (experiments ?? []).slice(0, input.limit),
      unavailable,
    };
  }

  /** Null when the group did not load (no scope, no product, or a failed call). */
  private async featureFlags(
    viewerId: number | null,
  ): Promise<HomeFeatureFlag[] | null> {
    const rows = await this.page<ApiFeatureFlag>(
      `feature_flags/?limit=${FLAG_PAGE_SIZE}&order=-created_at`,
      "list feature flags",
    );
    if (rows === null) return null;
    return rows
      .map((flag) => ({
        id: flag.id,
        key: flag.key,
        // The API's `name` field carries the flag's description.
        name: flag.name?.trim() || flag.key,
        active: flag.active ?? false,
        rolloutPercentage: rolloutPercentage(flag),
        hasExperiment: (flag.experiment_set?.length ?? 0) > 0,
        createdAt: epoch(flag.created_at) ?? 0,
        yours: viewerId != null && flag.created_by?.id === viewerId,
        createdBy: displayName(flag.created_by),
      }))
      .sort(rankByOwnershipThenRecency);
  }

  private async experiments(
    viewerId: number | null,
  ): Promise<HomeExperiment[] | null> {
    const rows = await this.page<ApiExperiment>(
      `experiments/?limit=${EXPERIMENT_PAGE_SIZE}`,
      "list experiments",
    );
    if (rows === null) return null;
    return rows
      .map((experiment) => ({
        id: experiment.id,
        name: experiment.name,
        description: experiment.description?.trim() || null,
        featureFlagKey: experiment.feature_flag_key ?? null,
        stage: toStage(experiment.status),
        startedAt: epoch(experiment.start_date),
        endedAt: epoch(experiment.end_date),
        variants: (experiment.parameters?.feature_flag_variants ?? [])
          .map((variant) => variant.key)
          .filter((key): key is string => !!key),
        yours: viewerId != null && experiment.created_by?.id === viewerId,
        createdBy: displayName(experiment.created_by),
        createdAt: epoch(experiment.created_at) ?? 0,
      }))
      .sort(rankExperiments)
      .map(({ createdAt: _createdAt, ...experiment }) => experiment);
  }

  /**
   * One page of a DRF collection. A failure is a missing group rather than an
   * error — the caller reports it as such, and Home renders around it.
   */
  private async page<T>(path: string, label: string): Promise<T[] | null> {
    try {
      const body = await this.api.json<{ results?: T[] }>(path, label);
      return body.results ?? [];
    } catch {
      return null;
    }
  }
}

function rankByOwnershipThenRecency(
  a: { yours: boolean; createdAt: number },
  b: { yours: boolean; createdAt: number },
): number {
  if (a.yours !== b.yours) return a.yours ? -1 : 1;
  return b.createdAt - a.createdAt;
}

/**
 * Running experiments lead — they are the ones with an outcome moving today —
 * then the viewer's own, then the most recently created.
 */
function rankExperiments(
  a: { stage: HomeExperimentStage; yours: boolean; createdAt: number },
  b: { stage: HomeExperimentStage; yours: boolean; createdAt: number },
): number {
  const stageOrder: Record<HomeExperimentStage, number> = {
    running: 0,
    paused: 1,
    draft: 2,
    concluded: 3,
  };
  if (a.stage !== b.stage) return stageOrder[a.stage] - stageOrder[b.stage];
  return rankByOwnershipThenRecency(a, b);
}
