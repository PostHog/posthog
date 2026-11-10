import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { waitForFile } from "./wait-for-file";

const directories: string[] = [];

afterEach(async () => {
  await Promise.all(
    directories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

describe("waitForFile", () => {
  it("returns immediately for an existing sentinel", async () => {
    const directory = await temporaryDirectory();
    const path = join(directory, "ready");
    await writeFile(path, "");

    await expect(waitForFile(path, { timeoutMs: 100 })).resolves.toEqual({
      waitedMs: 0,
      timedOut: false,
    });
  });

  it("wakes on creation instead of waiting for the fallback poll", async () => {
    const directory = await temporaryDirectory();
    const path = join(directory, "ready");
    const waiting = waitForFile(path, {
      timeoutMs: 1_000,
      fallbackPollMs: 500,
    });

    await writeFile(path, "");

    const result = await waiting;
    expect(result.timedOut).toBe(false);
    expect(result.waitedMs).toBeLessThan(500);
  });

  it("returns a bounded timeout result", async () => {
    const directory = await temporaryDirectory();
    const path = join(directory, "never-ready");

    const result = await waitForFile(path, {
      timeoutMs: 10,
      fallbackPollMs: 100,
    });

    expect(result.timedOut).toBe(true);
    expect(result.waitedMs).toBeGreaterThanOrEqual(10);
  });
});

async function temporaryDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "agent-ready-"));
  directories.push(directory);
  return directory;
}
