import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  addMissingCloudRuntimeConfigOptions,
  buildCloudDefaultConfigOptions,
  extractLatestConfigOptionsFromEntries,
} from "./cloudSessionConfig";

function configUpdateEntry(
  configOptions: unknown,
  sessionUpdate = "config_option_update",
): StoredLogEntry {
  return {
    type: "notification",
    notification: {
      method: "session/update",
      params: { update: { sessionUpdate, configOptions } },
    },
  } as unknown as StoredLogEntry;
}

describe("extractLatestConfigOptionsFromEntries", () => {
  it("returns undefined when no config_option_update entries exist", () => {
    expect(extractLatestConfigOptionsFromEntries([])).toBeUndefined();
    expect(
      extractLatestConfigOptionsFromEntries([
        configUpdateEntry([{ id: "mode" }], "agent_message"),
      ]),
    ).toBeUndefined();
  });

  it("returns the latest config options across multiple updates", () => {
    const result = extractLatestConfigOptionsFromEntries([
      configUpdateEntry([{ id: "mode", currentValue: "plan" }]),
      configUpdateEntry([{ id: "mode", currentValue: "auto" }]),
    ]);

    expect(result).toEqual([{ id: "mode", currentValue: "auto" }]);
  });
});

describe("buildCloudDefaultConfigOptions", () => {
  it("includes a mode select with options and the chosen current value", () => {
    const options = buildCloudDefaultConfigOptions("plan");
    const mode = options.find((o) => o.id === "mode");

    expect(mode?.currentValue).toBe("plan");
    if (mode?.type !== "select") {
      throw new Error("expected mode to be a select option");
    }
    expect(mode.options.length).toBeGreaterThan(0);
  });

  it("defaults claude sessions to plan and codex sessions to auto", () => {
    const claude = buildCloudDefaultConfigOptions(undefined, "claude");
    const codex = buildCloudDefaultConfigOptions(undefined, "codex");

    expect(claude.find((o) => o.id === "mode")?.currentValue).toBe("plan");
    expect(codex.find((o) => o.id === "mode")?.currentValue).toBe("auto");
  });

  it.each([
    { initialMode: "auto", expected: "auto" },
    { initialMode: "full-access", expected: "full-access" },
    // plan is now a valid codex preset (mirrors the app-server), so it's kept.
    { initialMode: "plan", expected: "plan" },
    { initialMode: "default", expected: "auto" },
  ])(
    "validates codex initial mode $initialMode",
    ({ initialMode, expected }) => {
      const options = buildCloudDefaultConfigOptions(initialMode, "codex");

      expect(options.find((o) => o.id === "mode")?.currentValue).toBe(expected);
    },
  );

  it("appends extra options after the mode option", () => {
    const extra = [
      {
        id: "model",
        name: "Model",
        type: "select" as const,
        currentValue: "x",
        options: [],
      },
    ];
    const options = buildCloudDefaultConfigOptions("plan", "claude", extra);

    expect(options[0].id).toBe("mode");
    expect(options.at(-1)?.id).toBe("model");
  });
});

describe("addMissingCloudRuntimeConfigOptions", () => {
  it("seeds selected model and reasoning values for codex cloud sessions", () => {
    const options = addMissingCloudRuntimeConfigOptions(
      buildCloudDefaultConfigOptions("auto", "codex"),
      "codex",
      "gpt-5.6-sol",
      "max",
    );

    expect(options).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "model",
          category: "model",
          currentValue: "gpt-5.6-sol",
        }),
        expect.objectContaining({
          id: "reasoning_effort",
          category: "thought_level",
          currentValue: "max",
        }),
      ]),
    );
  });

  it("keeps preview-provided runtime options unchanged", () => {
    const existing = buildCloudDefaultConfigOptions("plan", "claude", [
      {
        id: "model",
        name: "Model",
        type: "select",
        currentValue: "claude-opus-4-7",
        options: [{ value: "claude-opus-4-7", name: "Opus 4.7" }],
        category: "model",
      },
    ]);

    expect(
      addMissingCloudRuntimeConfigOptions(
        existing,
        "claude",
        "claude-sonnet-4-6",
      ),
    ).toBe(existing);
  });
});
