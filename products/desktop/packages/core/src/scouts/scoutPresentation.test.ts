import type { ScoutConfig, ScoutRun } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  buildScoutCreatorIndex,
  computeFleetSummary,
  computeScoutRollups,
  deriveRunFailureKind,
  deriveRunOutcome,
  deriveScoutLifecycle,
  formatRunDuration,
  formatRunInterval,
  formatRunIntervalShort,
  getScoutOrigin,
  isRunStuck,
  isScoutCreatedByUser,
  listScoutCreatorOptions,
  normalizeRunStatus,
  prettifyScoutSkillName,
  runDurationSeconds,
  runMatchesFilter,
  type ScoutOrigin,
  type ScoutRunFilter,
  scoutCreatorDisplayName,
  scoutCreatorKey,
  scoutRunOutcomeLabel,
  scoutSkillNameFromSlug,
  scoutSkillSlug,
  sortConfigsForDisplay,
} from "./scoutPresentation";

const NOW = new Date("2026-06-10T12:00:00Z");

function makeRun(overrides: Partial<ScoutRun> = {}): ScoutRun {
  return {
    run_id: "run-1",
    skill_name: "signals-scout-error-tracking",
    skill_version: 3,
    status: "completed",
    started_at: "2026-06-10T11:00:00Z",
    completed_at: "2026-06-10T11:02:00Z",
    task_id: null,
    task_run_id: null,
    task_url: null,
    summary: "EMITTED nothing.",
    emitted_count: 0,
    emitted_finding_ids: [],
    ...overrides,
  };
}

function makeConfig(overrides: Partial<ScoutConfig> = {}): ScoutConfig {
  return {
    id: "config-1",
    skill_name: "signals-scout-error-tracking",
    enabled: true,
    emit: true,
    run_interval_minutes: 60,
    last_run_at: "2026-06-10T11:00:00Z",
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

describe("naming", () => {
  it("prettifies skill names", () => {
    expect(prettifyScoutSkillName("signals-scout-error-tracking")).toBe(
      "Error tracking",
    );
    expect(prettifyScoutSkillName("signals-scout-ai-observability")).toBe(
      "Ai observability",
    );
    expect(prettifyScoutSkillName("custom_thing")).toBe("Custom thing");
  });

  it("round-trips slugs", () => {
    expect(scoutSkillSlug("signals-scout-error-tracking")).toBe(
      "error-tracking",
    );
    expect(scoutSkillNameFromSlug("error-tracking")).toBe(
      "signals-scout-error-tracking",
    );
    expect(scoutSkillNameFromSlug("signals-scout-error-tracking")).toBe(
      "signals-scout-error-tracking",
    );
  });

  it.each<[Pick<ScoutConfig, "scout_origin"> | null | undefined, ScoutOrigin]>([
    [{ scout_origin: "canonical" }, "canonical"],
    [{ scout_origin: "custom" }, "custom"],
    // A missing field (older backends) or no config falls back to custom.
    [{}, "custom"],
    [null, "custom"],
    [undefined, "custom"],
  ])("getScoutOrigin(%o) returns %s", (input, expected) => {
    expect(getScoutOrigin(input)).toBe(expected);
  });
});

describe("run status", () => {
  it.each([
    ["COMPLETED", "completed"],
    ["failed", "failed"],
    ["IN_PROGRESS", "running"],
    ["queued", "queued"],
    ["something-else", "unknown"],
  ])("normalizes TaskRun status %s to %s", (raw, normalized) => {
    expect(normalizeRunStatus(raw)).toBe(normalized);
  });

  it("computes duration, falling back to now for unfinished runs", () => {
    expect(runDurationSeconds(makeRun(), NOW)).toBe(120);
    const running = makeRun({
      status: "in_progress",
      started_at: "2026-06-10T11:58:00Z",
      completed_at: null,
    });
    expect(runDurationSeconds(running, NOW)).toBe(120);
    expect(runDurationSeconds(makeRun({ started_at: null }), NOW)).toBeNull();
  });

  it.each([
    [42, "42s"],
    [134, "2m 14s"],
    [3 * 3600, "3h"],
    [null, ""],
  ])("formats a duration of %s seconds as %j", (seconds, label) => {
    expect(formatRunDuration(seconds)).toBe(label);
  });

  it("classifies long failed runs as timeouts", () => {
    const timedOut = makeRun({
      status: "failed",
      started_at: "2026-06-10T11:00:00Z",
      completed_at: "2026-06-10T11:30:10Z",
      summary: "",
    });
    expect(deriveRunFailureKind(timedOut, NOW)).toBe("timed_out");
    const errored = makeRun({
      status: "failed",
      completed_at: "2026-06-10T11:00:30Z",
    });
    expect(deriveRunFailureKind(errored, NOW)).toBe("error");
    expect(deriveRunFailureKind(makeRun(), NOW)).toBeNull();
  });

  it("flags in-progress runs past the deadline as stuck", () => {
    const stuck = makeRun({
      status: "in_progress",
      started_at: "2026-06-10T11:20:00Z",
      completed_at: null,
    });
    expect(isRunStuck(stuck, NOW)).toBe(true);
    const fresh = makeRun({
      status: "in_progress",
      started_at: "2026-06-10T11:55:00Z",
      completed_at: null,
    });
    expect(isRunStuck(fresh, NOW)).toBe(false);
    expect(isRunStuck(makeRun(), NOW)).toBe(false);
  });
});

describe("run outcomes", () => {
  it.each<{
    overrides: Partial<ScoutRun>;
    outcome: ReturnType<typeof deriveRunOutcome>;
  }>([
    { overrides: { emitted_count: 2 }, outcome: "emitted" },
    { overrides: { emitted_count: 0 }, outcome: "quiet" },
    {
      overrides: { status: "failed", completed_at: "2026-06-10T11:00:30Z" },
      outcome: "error",
    },
    {
      overrides: { status: "failed", completed_at: "2026-06-10T11:30:10Z" },
      outcome: "timed_out",
    },
    {
      overrides: {
        status: "in_progress",
        started_at: "2026-06-10T11:55:00Z",
        completed_at: null,
      },
      outcome: "running",
    },
    {
      overrides: {
        status: "in_progress",
        started_at: "2026-06-10T11:20:00Z",
        completed_at: null,
      },
      outcome: "stuck",
    },
    { overrides: { status: "queued" }, outcome: "queued" },
  ])("classifies the run as $outcome", ({ overrides, outcome }) => {
    expect(deriveRunOutcome(makeRun(overrides), NOW)).toBe(outcome);
  });

  it.each<{ overrides: Partial<ScoutRun>; label: string }>([
    { overrides: { emitted_count: 1 }, label: "1 signal emitted" },
    { overrides: { emitted_count: 0 }, label: "0 signals emitted" },
    {
      overrides: { status: "failed", completed_at: "2026-06-10T11:30:10Z" },
      label: "timed out",
    },
  ])('labels the outcome "$label"', ({ overrides, label }) => {
    expect(scoutRunOutcomeLabel(makeRun(overrides), NOW)).toBe(label);
  });
});

describe("run filters", () => {
  const emitted = makeRun({ emitted_count: 2 });
  const quiet = makeRun({ emitted_count: 0 });
  const failed = makeRun({ status: "failed", emitted_count: 0 });

  it.each<{
    name: string;
    run: ScoutRun;
    filter: ScoutRunFilter;
    matches: boolean;
  }>([
    { name: "emitted", run: emitted, filter: "emitted", matches: true },
    { name: "quiet", run: quiet, filter: "emitted", matches: false },
    { name: "quiet", run: quiet, filter: "quiet", matches: true },
    { name: "failed", run: failed, filter: "quiet", matches: false },
    { name: "failed", run: failed, filter: "failed", matches: true },
    { name: "emitted", run: emitted, filter: "all", matches: true },
  ])(
    "$name run matching the $filter chip is $matches",
    ({ run, filter, matches }) => {
      expect(runMatchesFilter(run, filter)).toBe(matches);
    },
  );
});

describe("rollups", () => {
  it("aggregates per-scout counts and tracks latest/running runs", () => {
    const runs = [
      makeRun({ run_id: "a", started_at: "2026-06-10T10:00:00Z" }),
      makeRun({
        run_id: "b",
        started_at: "2026-06-10T11:00:00Z",
        emitted_count: 2,
      }),
      makeRun({
        run_id: "c",
        status: "failed",
        started_at: "2026-06-10T09:00:00Z",
      }),
      makeRun({
        run_id: "d",
        skill_name: "signals-scout-logs",
        status: "in_progress",
        started_at: "2026-06-10T11:58:00Z",
        completed_at: null,
      }),
    ];
    const rollups = computeScoutRollups(runs);
    const errorTracking = rollups.get("signals-scout-error-tracking");
    expect(errorTracking).toMatchObject({
      runCount: 3,
      completedCount: 2,
      failedCount: 1,
      emittedCount: 2,
    });
    expect(errorTracking?.latestRun?.run_id).toBe("b");
    expect(errorTracking?.runningRun).toBeNull();
    expect(rollups.get("signals-scout-logs")?.runningRun?.run_id).toBe("d");
    expect(errorTracking?.runs.map((run) => run.run_id)).toEqual([
      "c",
      "a",
      "b",
    ]);
  });

  it("computes the fleet summary", () => {
    const configs = [
      makeConfig(),
      makeConfig({
        id: "config-2",
        skill_name: "signals-scout-logs",
        enabled: false,
      }),
    ];
    const rollups = computeScoutRollups([
      makeRun({ emitted_count: 2 }),
      makeRun({ run_id: "x", status: "failed" }),
    ]);
    const summary = computeFleetSummary(configs, rollups);
    expect(summary).toMatchObject({
      totalCount: 2,
      enabledCount: 1,
      runningCount: 0,
      emittedCount: 2,
    });
    expect(summary.successRate).toBe(0.5);
    expect(summary.emitRate).toBe(0.5);
  });

  it("returns null rates with no runs", () => {
    const summary = computeFleetSummary([], computeScoutRollups([]));
    expect(summary.successRate).toBeNull();
    expect(summary.emitRate).toBeNull();
  });

  it("counts only the warnings that actually pause, plus system pauses", () => {
    const configs = [
      makeConfig({ status: "active" }),
      // Quiet: flagged, but the sweep never escalates it, so it must not be
      // counted as pausing soon.
      makeConfig({
        id: "config-2",
        skill_name: "signals-scout-logs",
        status: "pending_pause",
        pause_reason: "no_output",
      }),
      makeConfig({
        id: "config-3",
        skill_name: "signals-scout-quiet",
        status: "pending_pause",
        pause_reason: "ignored",
      }),
      makeConfig({
        id: "config-4",
        skill_name: "signals-scout-apm",
        enabled: false,
        status: "paused_by_system",
        pause_reason: "repeated_failures",
      }),
      makeConfig({
        id: "config-5",
        skill_name: "signals-scout-surveys",
        enabled: false,
        status: "paused_by_user",
      }),
    ];
    expect(computeFleetSummary(configs, computeScoutRollups([]))).toMatchObject(
      {
        totalCount: 5,
        enabledCount: 3,
        pausingSoonCount: 1,
        systemPausedCount: 1,
      },
    );
  });
});

describe("intervals and ordering", () => {
  it.each([
    [60, "Hourly"],
    [90, "Every 90 minutes"],
    [2880, "Every 2 days"],
  ])("formats a %i-minute interval as %s", (minutes, label) => {
    expect(formatRunInterval(minutes)).toBe(label);
  });

  it.each([
    [60, "hourly"],
    [180, "every 3h"],
  ])("formats a %i-minute interval as %s in short form", (minutes, label) => {
    expect(formatRunIntervalShort(minutes)).toBe(label);
  });

  it("sorts enabled scouts first, then alphabetically", () => {
    const configs = [
      makeConfig({ skill_name: "signals-scout-logs", enabled: false }),
      makeConfig({ skill_name: "signals-scout-surveys" }),
      makeConfig({ skill_name: "signals-scout-error-tracking" }),
    ];
    expect(
      sortConfigsForDisplay(configs).map((config) => config.skill_name),
    ).toEqual([
      "signals-scout-error-tracking",
      "signals-scout-surveys",
      "signals-scout-logs",
    ]);
  });

  it("leads the off-block with system-paused scouts", () => {
    const configs = [
      makeConfig({ skill_name: "signals-scout-apm", enabled: false }),
      makeConfig({
        skill_name: "signals-scout-logs",
        enabled: false,
        status: "paused_by_system",
        pause_reason: "repeated_failures",
      }),
      makeConfig({ skill_name: "signals-scout-surveys" }),
    ];
    expect(
      sortConfigsForDisplay(configs).map((config) => config.skill_name),
    ).toEqual([
      "signals-scout-surveys",
      "signals-scout-logs",
      "signals-scout-apm",
    ]);
  });
});

describe("lifecycle", () => {
  it.each([
    ["ignored", "unacted on"],
    ["no_output", "stopped emitting"],
    ["repeated_failures", "3 runs in a row failed"],
  ] as const)("explains a %s system pause", (reason, fragment) => {
    const state = deriveScoutLifecycle(
      makeConfig({
        enabled: false,
        status: "paused_by_system",
        pause_reason: reason,
        consecutive_failure_count: 3,
        status_changed_at: "2026-06-09T00:00:00Z",
      }),
    );
    expect(state).toMatchObject({
      lifecycle: "paused_by_system",
      label: "Auto-paused",
      isSystemPaused: true,
      isWarned: false,
      changedAt: "2026-06-09T00:00:00Z",
    });
    expect(state.explanation).toContain(fragment);
    // Re-enabling is the recovery on every reason, so it always gets named.
    expect(state.explanation).toMatch(/switch it back on/i);
  });

  it("says an inactivity pause never lifts itself", () => {
    // The sweep has no probe: a human re-enable is the only exit, and the copy
    // must not promise the permanent exemption a resume no longer mints.
    const state = deriveScoutLifecycle(
      makeConfig({
        enabled: false,
        status: "paused_by_system",
        pause_reason: "ignored",
      }),
    );
    expect(state.explanation).toContain("can pause again later");
    expect(state.explanation).not.toMatch(/retries|on its own|exempt/i);
  });

  it("says a failure pause retries on its own", () => {
    // The breaker keeps a half-open probe, so presenting a manual re-enable as
    // the only way back would be wrong.
    const state = deriveScoutLifecycle(
      makeConfig({
        enabled: false,
        status: "paused_by_system",
        pause_reason: "repeated_failures",
        consecutive_failure_count: 6,
      }),
    );
    expect(state.explanation).toContain("resumes on its own");
  });

  it("flags an ignored warning as heading for a pause", () => {
    const state = deriveScoutLifecycle(
      makeConfig({ status: "pending_pause", pause_reason: "ignored" }),
    );
    expect(state).toMatchObject({
      lifecycle: "warned",
      label: "Pausing soon",
      isWarned: true,
      isSystemPaused: false,
      willPause: true,
    });
    expect(state.explanation).toContain("exempt it from inactivity pauses");
  });

  it("does not promise a pause for a quiet scout", () => {
    // `no_output` is warning-only on the backend: silence alone never pauses a
    // scout, because a watchdog's silence is the job.
    const state = deriveScoutLifecycle(
      makeConfig({ status: "pending_pause", pause_reason: "no_output" }),
    );
    expect(state).toMatchObject({
      lifecycle: "warned",
      label: "Quiet",
      isWarned: true,
      willPause: false,
    });
    expect(state.explanation).not.toMatch(/will pause|pausing soon/i);
  });

  it.each([
    [true, "active"],
    [false, "paused_by_user"],
  ] as const)(
    "badges nothing for an enabled=%s scout with no system action",
    (enabled, lifecycle) => {
      expect(
        deriveScoutLifecycle(
          makeConfig({
            enabled,
            status: enabled ? "active" : "paused_by_user",
          }),
        ),
      ).toMatchObject({ lifecycle, label: null, explanation: null });
    },
  );

  it("clears the pause as soon as the scout is switched back on", () => {
    // The optimistic enable patches `enabled` alone; the server clears `status`
    // on the response, so the badge must not survive the round trip.
    expect(
      deriveScoutLifecycle(
        makeConfig({
          enabled: true,
          status: "paused_by_system",
          pause_reason: "repeated_failures",
        }),
      ),
    ).toMatchObject({ lifecycle: "active", label: null, explanation: null });
  });

  it("falls back to enabled on backends predating the lifecycle fields", () => {
    expect(deriveScoutLifecycle(makeConfig({ enabled: false }))).toMatchObject({
      lifecycle: "paused_by_user",
      label: null,
      // Null, not false: an absent field cannot be written back, so the UI has
      // to be able to tell "unsupported" from "off".
      autoPauseExempt: null,
      consecutiveFailureCount: 0,
    });
  });

  it.each([
    [true, true],
    [false, false],
  ])("reads auto_pause_exempt=%s as %s", (sent, expected) => {
    expect(
      deriveScoutLifecycle(makeConfig({ auto_pause_exempt: sent })),
    ).toMatchObject({ autoPauseExempt: expected });
  });
});

describe("creators", () => {
  it("indexes latest authored skills and skips canonical seeds", () => {
    const index = buildScoutCreatorIndex([
      {
        name: "signals-scout-ad-spend",
        created_by: { id: 7, email: "paul@example.com" },
        is_latest: true,
      },
      // Canonical seeds carry no author.
      {
        name: "signals-scout-error-tracking",
        created_by: null,
        is_latest: true,
      },
      // Superseded versions must not shadow the latest author.
      {
        name: "signals-scout-ad-spend",
        created_by: { id: 9, email: "someone@example.com" },
        is_latest: false,
      },
    ]);
    expect(index.get("signals-scout-ad-spend")).toEqual({
      id: 7,
      email: "paul@example.com",
    });
    expect(index.has("signals-scout-error-tracking")).toBe(false);
  });

  it.each<{
    label: string;
    creator: Parameters<typeof isScoutCreatedByUser>[0];
    user: Parameters<typeof isScoutCreatedByUser>[1];
    expected: boolean;
  }>([
    {
      label: "matches on numeric id",
      creator: { id: 7, email: "old@example.com" },
      user: { id: 7, email: "new@example.com" },
      expected: true,
    },
    {
      label: "rejects a different id even when emails collide",
      creator: { id: 7, email: "shared@example.com" },
      user: { id: 8, email: "shared@example.com" },
      expected: false,
    },
    {
      label: "falls back to case-insensitive email when the id is absent",
      creator: { email: "Paul@Example.com" },
      user: { id: 7, email: "paul@example.com" },
      expected: true,
    },
    {
      label: "never matches an unauthored scout",
      creator: undefined,
      user: { id: 7, email: "paul@example.com" },
      expected: false,
    },
    {
      label: "never matches without a user",
      creator: { id: 7 },
      user: null,
      expected: false,
    },
    {
      label: "never matches on missing emails",
      creator: { email: null },
      user: { email: "" },
      expected: false,
    },
  ])("$label", ({ creator, user, expected }) => {
    expect(isScoutCreatedByUser(creator, user)).toBe(expected);
  });

  it("keys creators by numeric id, falling back to normalized email", () => {
    expect(scoutCreatorKey({ id: 7, email: "x@example.com" })).toBe("id:7");
    expect(scoutCreatorKey({ email: " Paul@Example.com " })).toBe(
      "email:paul@example.com",
    );
    expect(scoutCreatorKey({})).toBeNull();
    expect(scoutCreatorKey(null)).toBeNull();
  });

  it("prefers the full name for display, then the email", () => {
    expect(
      scoutCreatorDisplayName({
        first_name: "Paul",
        last_name: "Smith",
        email: "p@example.com",
      }),
    ).toBe("Paul Smith");
    expect(scoutCreatorDisplayName({ email: "p@example.com" })).toBe(
      "p@example.com",
    );
    expect(scoutCreatorDisplayName({})).toBe("Unknown user");
  });

  describe("listScoutCreatorOptions", () => {
    const index = buildScoutCreatorIndex([
      {
        name: "signals-scout-ad-spend",
        created_by: { id: 7, first_name: "Paul", email: "paul@example.com" },
        is_latest: true,
      },
      {
        name: "signals-scout-checkout",
        created_by: { id: 9, first_name: "Zoe", email: "zoe@example.com" },
        is_latest: true,
      },
      {
        name: "signals-scout-digest",
        created_by: { id: 8, first_name: "Amy", email: "amy@example.com" },
        is_latest: true,
      },
      // A second skill by an existing author must not duplicate the option.
      {
        name: "signals-scout-uptime",
        created_by: { id: 9, first_name: "Zoe", email: "zoe@example.com" },
        is_latest: true,
      },
    ]);

    it("pins the current user first and sorts the rest alphabetically", () => {
      const options = listScoutCreatorOptions(index, {
        id: 7,
        email: "paul@example.com",
      });
      expect(options.map((option) => option.label)).toEqual([
        "Paul (you)",
        "Amy",
        "Zoe",
      ]);
      expect(options[0]).toMatchObject({ key: "id:7", isCurrentUser: true });
    });

    it("still offers the current user when they authored nothing", () => {
      const options = listScoutCreatorOptions(index, {
        id: 1,
        first_name: "New",
        email: "new@example.com",
      });
      expect(options[0]).toEqual({
        key: "id:1",
        label: "New (you)",
        isCurrentUser: true,
      });
      expect(options).toHaveLength(4);
    });

    it("lists plain authors when the current user is unknown", () => {
      const options = listScoutCreatorOptions(index, null);
      expect(options.map((option) => option.label)).toEqual([
        "Amy",
        "Paul",
        "Zoe",
      ]);
      expect(options.every((option) => !option.isCurrentUser)).toBe(true);
    });
  });
});
