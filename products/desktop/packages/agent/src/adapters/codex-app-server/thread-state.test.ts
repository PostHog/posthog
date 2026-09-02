import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { hasCodexThreadState } from "./thread-state";

const THREAD_ID = "0199a5c3-2f60-7b21-9c39-1d2e3f4a5b6c";

describe("hasCodexThreadState", () => {
  let codexHome: string;

  beforeEach(async () => {
    codexHome = await mkdtemp(join(tmpdir(), "codex-home-"));
    vi.stubEnv("CODEX_HOME", codexHome);
  });

  afterEach(async () => {
    vi.unstubAllEnvs();
    await rm(codexHome, { recursive: true, force: true });
  });

  const writeRollout = async (threadId: string) => {
    const dir = join(codexHome, "sessions", "2026", "07", "07");
    await mkdir(dir, { recursive: true });
    await writeFile(
      join(dir, `rollout-2026-07-07T10-00-00-${threadId}.jsonl`),
      "",
    );
  };

  it.each([
    [true, "the persisted thread id", THREAD_ID],
    [false, "a different thread id", "11111111-2222-3333-4444-555555555555"],
    [false, "an empty thread id", ""],
  ])("returns %s querying %s", async (expected, _case, queriedId) => {
    await writeRollout(THREAD_ID);
    await expect(hasCodexThreadState(queriedId)).resolves.toBe(expected);
  });

  it("returns false when there is no sessions directory", async () => {
    await expect(hasCodexThreadState(THREAD_ID)).resolves.toBe(false);
  });

  it("ignores files that are not rollouts", async () => {
    const dir = join(codexHome, "sessions", "2026", "07", "07");
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, `notes-${THREAD_ID}.jsonl`), "");
    await expect(hasCodexThreadState(THREAD_ID)).resolves.toBe(false);
  });
});
