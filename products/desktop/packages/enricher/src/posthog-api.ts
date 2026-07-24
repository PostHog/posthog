import type {
  EnricherApiConfig,
  EventDefinition,
  EventStats,
  Experiment,
  FeatureFlag,
  FlagEvaluationStats,
} from "./types.js";

export class PostHogApi {
  private config: EnricherApiConfig;

  constructor(config: EnricherApiConfig) {
    this.config = config;
  }

  private get baseUrl(): string {
    const host = this.config.host.replace(/\/$/, "");
    return `${host}/api/projects/${this.config.projectId}`;
  }

  private get signal(): AbortSignal {
    return AbortSignal.timeout(this.config.timeoutMs ?? 10_000);
  }

  private async get<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      headers: {
        Authorization: `Bearer ${this.config.apiKey}`,
        "Content-Type": "application/json",
      },
      signal: this.signal,
    });
    if (!res.ok) {
      throw new Error(
        `PostHog API error: ${res.status} ${res.statusText} on GET ${path}`,
      );
    }
    return res.json() as Promise<T>;
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.config.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: this.signal,
    });
    if (!res.ok) {
      throw new Error(
        `PostHog API error: ${res.status} ${res.statusText} on POST ${path}`,
      );
    }
    return res.json() as Promise<T>;
  }

  async getFeatureFlags(): Promise<FeatureFlag[]> {
    const data = await this.get<{ results: FeatureFlag[] }>(
      "/feature_flags/?limit=500",
    );
    return data.results.filter((f) => !f.deleted);
  }

  // Keys absent from the returned map have NOT been called in the window.
  async getFlagLastCalled(
    flagKeys: string[],
    daysBack = 30,
  ): Promise<Map<string, string>> {
    if (flagKeys.length === 0) return new Map();

    // HogQL over `/query/` rejects typed placeholders (`{name:Type}`) and
    // placeholder values in INTERVAL, so `days` is inlined (clamped).
    const days = Math.max(1, Math.min(365, Math.floor(daysBack)));
    const query = `
      SELECT
        properties.$feature_flag AS flag_key,
        max(timestamp) AS last_called_at
      FROM events
      WHERE event = '$feature_flag_called'
        AND properties.$feature_flag IN {flagKeys}
        AND timestamp >= now() - INTERVAL ${days} DAY
      GROUP BY flag_key
    `;

    const data = await this.post<{ results: [string, string][] }>("/query/", {
      query: {
        kind: "HogQLQuery",
        query,
        values: { flagKeys },
      },
    });

    const lastCalled = new Map<string, string>();
    for (const [flagKey, lastCalledAt] of data.results) {
      if (lastCalledAt) lastCalled.set(flagKey, lastCalledAt);
    }
    return lastCalled;
  }

  async getExperiments(): Promise<Experiment[]> {
    const data = await this.get<{ results: Experiment[] }>(
      "/experiments/?limit=500",
    );
    return data.results;
  }

  async getEventDefinitions(names?: string[]): Promise<EventDefinition[]> {
    let path = "/event_definitions/?limit=500";
    if (names && names.length > 0) {
      path += `&search=${encodeURIComponent(names.join(","))}`;
    }
    const data = await this.get<{ results: EventDefinition[] }>(path);
    return data.results;
  }

  async getEventStats(
    eventNames: string[],
    daysBack = 30,
  ): Promise<Map<string, EventStats>> {
    if (eventNames.length === 0) {
      return new Map();
    }

    // HogQL over `/query/` rejects typed placeholders (`{name:Type}`) and
    // placeholder values in INTERVAL, so `days` is inlined (clamped).
    const days = Math.max(1, Math.min(365, Math.floor(daysBack)));
    const query = `
      SELECT
        event,
        count() AS volume,
        count(DISTINCT person_id) AS unique_users,
        max(timestamp) AS last_seen
      FROM events
      WHERE event IN {eventNames}
        AND timestamp >= now() - INTERVAL ${days} DAY
      GROUP BY event
    `;

    const data = await this.post<{
      results: [string, number, number, string][];
    }>("/query/", {
      query: {
        kind: "HogQLQuery",
        query,
        values: { eventNames },
      },
    });

    const stats = new Map<string, EventStats>();
    for (const [event, volume, uniqueUsers, lastSeen] of data.results) {
      stats.set(event, {
        volume,
        uniqueUsers,
        lastSeenAt: lastSeen || null,
      });
    }
    return stats;
  }

  async getFlagEvaluationStats(
    flagKeys: string[],
    daysBack = 7,
  ): Promise<Map<string, FlagEvaluationStats>> {
    if (flagKeys.length === 0) {
      return new Map();
    }

    // HogQL over `/query/` rejects typed placeholders (`{name:Type}`) and
    // placeholder values in INTERVAL, so `days` is inlined (clamped).
    const days = Math.max(1, Math.min(365, Math.floor(daysBack)));
    const query = `
      SELECT
        properties.$feature_flag AS flag_key,
        count() AS evaluations,
        count(DISTINCT person_id) AS unique_users
      FROM events
      WHERE event = '$feature_flag_called'
        AND properties.$feature_flag IN {flagKeys}
        AND timestamp >= now() - INTERVAL ${days} DAY
      GROUP BY flag_key
    `;

    const data = await this.post<{
      results: [string, number, number][];
    }>("/query/", {
      query: {
        kind: "HogQLQuery",
        query,
        values: { flagKeys },
      },
    });

    const stats = new Map<string, FlagEvaluationStats>();
    for (const [flagKey, evaluations, uniqueUsers] of data.results) {
      stats.set(flagKey, { evaluations, uniqueUsers, windowDays: days });
    }
    return stats;
  }
}
