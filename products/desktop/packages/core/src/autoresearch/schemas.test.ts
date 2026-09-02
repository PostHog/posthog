import { describe, expect, it, vi } from "vitest";
import {
  AUTORESEARCH_MAX_ITERATIONS_LIMIT,
  autoresearchConfigSchema,
  parseStoredAutoresearchRun,
} from "./schemas";

const validInput = {
  taskId: "task-1",
  direction: "minimize" as const,
  instructions: "Shrink the production bundle.",
};

describe("autoresearchConfigSchema", () => {
  it("parses a minimal config and applies defaults", () => {
    const config = autoresearchConfigSchema.parse(validInput);
    expect(config.targetValue).toBeNull();
    expect(config.maxIterations).toBe(10);
    expect(config.implementModel).toBeNull();
    expect(config.measureModel).toBeNull();
  });

  it("trims instructions", () => {
    const config = autoresearchConfigSchema.parse({
      ...validInput,
      instructions: "  Reduce it.  ",
    });
    expect(config.instructions).toBe("Reduce it.");
  });

  it("accepts stage models", () => {
    const config = autoresearchConfigSchema.parse({
      ...validInput,
      implementModel: "claude-opus-4-8",
      measureModel: "claude-haiku-4-5",
    });
    expect(config.implementModel).toBe("claude-opus-4-8");
    expect(config.measureModel).toBe("claude-haiku-4-5");
  });

  it.each([
    ["empty instructions", { ...validInput, instructions: "" }],
    ["empty task id", { ...validInput, taskId: "" }],
    ["unknown direction", { ...validInput, direction: "increase" }],
    ["zero max iterations", { ...validInput, maxIterations: 0 }],
    ["fractional max iterations", { ...validInput, maxIterations: 2.5 }],
    [
      "max iterations above the limit",
      { ...validInput, maxIterations: AUTORESEARCH_MAX_ITERATIONS_LIMIT + 1 },
    ],
    ["non-finite target", { ...validInput, targetValue: Number.NaN }],
  ])("rejects %s", (_name, input) => {
    expect(autoresearchConfigSchema.safeParse(input).success).toBe(false);
  });

  it("accepts an explicit target and iteration budget", () => {
    const config = autoresearchConfigSchema.parse({
      ...validInput,
      targetValue: 150,
      maxIterations: 25,
    });
    expect(config.targetValue).toBe(150);
    expect(config.maxIterations).toBe(25);
  });
});

describe("parseStoredAutoresearchRun", () => {
  const storedRun = (status: string) =>
    JSON.stringify({
      id: "ar-1",
      config: { ...validInput, targetValue: null, maxIterations: 10 },
      status,
      metricName: null,
      phase: null,
      iterations: [],
      startedAt: 1,
      endedAt: null,
      endReason: null,
      interruptedReason: null,
      lastError: null,
    });

  it("restores a paused run as-is", () => {
    const run = parseStoredAutoresearchRun(storedRun("paused"));
    expect(run?.status).toBe("paused");
    expect(run?.interruptedReason).toBeNull();
  });

  it("restores a running run as a paused app-restart interruption", () => {
    vi.setSystemTime(20_000);
    const run = parseStoredAutoresearchRun(storedRun("running"));
    expect(run?.status).toBe("interrupted");
    expect(run?.interruptedReason).toBe("app-restart");
    expect(run?.pausedAt).toBe(20_000);
    expect(run?.pausedDurationMs).toBe(0);
  });

  it("defaults interruptedReason for blobs persisted before the field existed", () => {
    const legacy = JSON.parse(storedRun("paused"));
    delete legacy.interruptedReason;
    expect(parseStoredAutoresearchRun(JSON.stringify(legacy))?.status).toBe(
      "paused",
    );
  });

  it("defaults research findings for legacy persisted runs", () => {
    const run = parseStoredAutoresearchRun(storedRun("paused"));
    expect(run?.researchFindings).toEqual([]);
  });

  it.each([
    ["corrupt JSON", "{nope"],
    ["schema mismatch", JSON.stringify({ id: "ar-1" })],
  ])("returns null for %s", (_name, data) => {
    expect(parseStoredAutoresearchRun(data)).toBeNull();
  });
});
