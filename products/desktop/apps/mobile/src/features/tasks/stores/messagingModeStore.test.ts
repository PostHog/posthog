import { beforeEach, describe, expect, it } from "vitest";
import {
  type MessagingMode,
  migrateMessagingModeState,
  useMessagingModeStore,
} from "./messagingModeStore";

const INITIAL_STATE = useMessagingModeStore.getState();

const migrate = useMessagingModeStore.persist.getOptions().migrate as (
  persisted: unknown,
  version: number,
) => {
  modesByTaskId: Record<string, MessagingMode>;
  defaultMode: MessagingMode;
};

describe("messagingModeStore", () => {
  beforeEach(() => {
    useMessagingModeStore.setState(
      { ...INITIAL_STATE, modesByTaskId: {}, defaultMode: "steer" },
      true,
    );
  });

  it("defaults to Steer", () => {
    expect(useMessagingModeStore.getState().getEffectiveMode("t1")).toBe(
      "steer",
    );
  });

  it.each(["queue", "steer"] as const)(
    "falls back to the global default (%s) when a task has no override",
    (mode) => {
      useMessagingModeStore.getState().setDefaultMode(mode);
      expect(useMessagingModeStore.getState().getEffectiveMode("t1")).toBe(
        mode,
      );
    },
  );

  it("prefers a per-task override over the global default", () => {
    useMessagingModeStore.getState().setMode("t1", "queue");
    expect(useMessagingModeStore.getState().getEffectiveMode("t1")).toBe(
      "queue",
    );
    // A different task still resolves to the global default.
    expect(useMessagingModeStore.getState().getEffectiveMode("t2")).toBe(
      "steer",
    );
  });

  it("treats an undefined taskId as the global default", () => {
    useMessagingModeStore.getState().setDefaultMode("queue");
    expect(useMessagingModeStore.getState().getEffectiveMode(undefined)).toBe(
      "queue",
    );
  });

  // Exercises the migration through the persisted store's wired `migrate`
  // option, complementing the direct unit tests below.
  describe("migration", () => {
    it.each([
      {
        name: "flips a pre-v1 queue default to steer",
        version: 0,
        from: "queue",
        expected: "steer",
      },
      {
        name: "does not clobber a queue default set at the current version",
        version: 1,
        from: "queue",
        expected: "queue",
      },
      {
        name: "leaves a pre-v1 steer default untouched",
        version: 0,
        from: "steer",
        expected: "steer",
      },
    ] as const)("$name", ({ version, from, expected }) => {
      const migrated = migrate(
        { modesByTaskId: {}, defaultMode: from },
        version,
      );
      expect(migrated.defaultMode).toBe(expected);
    });

    it("preserves per-task overrides through migration", () => {
      const migrated = migrate(
        { modesByTaskId: { t1: "queue", t2: "steer" }, defaultMode: "queue" },
        0,
      );
      expect(migrated.modesByTaskId).toEqual({ t1: "queue", t2: "steer" });
      expect(migrated.defaultMode).toBe("steer");
    });
  });
});

describe("migrateMessagingModeState", () => {
  it("moves v0 installs to steer while keeping per-task overrides", () => {
    const migrated = migrateMessagingModeState(
      { modesByTaskId: { t1: "queue" }, defaultMode: "queue" },
      0,
    );
    expect(migrated).toEqual({
      modesByTaskId: { t1: "queue" },
      defaultMode: "steer",
    });
  });

  it("leaves already-migrated state untouched", () => {
    const state = { modesByTaskId: {}, defaultMode: "queue" as const };
    expect(migrateMessagingModeState(state, 1)).toEqual(state);
  });

  it("tolerates missing persisted state", () => {
    expect(migrateMessagingModeState(undefined, 0)).toEqual({
      defaultMode: "steer",
    });
  });
});
