import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createGitClient } from "./client";
import { streamGitStatus } from "./status-stream";

async function setupRepo(): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "posthog-code-status-stream-"));
  const git = createGitClient(dir);
  await git.init(["--initial-branch", "main"]);
  await git.addConfig("user.name", "Test");
  await git.addConfig("user.email", "test@example.com");
  await git.addConfig("commit.gpgsign", "false");
  await writeFile(path.join(dir, "file.txt"), "content\n");
  await git.add(["file.txt"]);
  await git.commit("initial");
  return dir;
}

describe("streamGitStatus", () => {
  let repoDir: string;

  afterEach(async () => {
    if (repoDir) await rm(repoDir, { recursive: true, force: true });
  });

  it("returns clean status for an unmodified repo", async () => {
    repoDir = await setupRepo();
    const status = await streamGitStatus(repoDir);
    expect(status.isClean).toBe(true);
    expect(status.untracked).toEqual([]);
    expect(status.overflowedDirs).toEqual([]);
  });

  it("collapses a directory whose untracked file count exceeds the per-dir cap", async () => {
    repoDir = await setupRepo();
    const heavy = path.join(repoDir, "node_modules", "pkg");
    await mkdir(heavy, { recursive: true });
    await Promise.all(
      Array.from({ length: 50 }, (_, i) =>
        writeFile(path.join(heavy, `f${i}.js`), "x"),
      ),
    );
    await writeFile(path.join(repoDir, "feature.ts"), "ok\n");

    const status = await streamGitStatus(repoDir, { perDirUntrackedCap: 10 });

    expect(status.untracked).toContain("feature.ts");
    expect(status.overflowedDirs.length).toBeGreaterThan(0);
    const filesUnderHeavy = status.untracked.filter((f) =>
      f.startsWith("node_modules/"),
    );
    expect(filesUnderHeavy.length).toBeLessThanOrEqual(10);
    expect(status.totalUntrackedSeen).toBeGreaterThanOrEqual(51);
  });

  it("keeps a folder fully expanded when its untracked count is within the cap", async () => {
    repoDir = await setupRepo();
    const feature = path.join(repoDir, "apps", "new-feature");
    await mkdir(feature, { recursive: true });
    await Promise.all(
      Array.from({ length: 8 }, (_, i) =>
        writeFile(path.join(feature, `mod-${i}.ts`), "x"),
      ),
    );

    const status = await streamGitStatus(repoDir, { perDirUntrackedCap: 1000 });

    const featureFiles = status.untracked.filter((f) =>
      f.startsWith("apps/new-feature/"),
    );
    expect(featureFiles).toHaveLength(8);
    expect(status.overflowedDirs).toEqual([]);
  });

  it("reports modified, staged, and deleted entries", async () => {
    repoDir = await setupRepo();
    const git = createGitClient(repoDir);
    await writeFile(path.join(repoDir, "staged.txt"), "s\n");
    await git.add(["staged.txt"]);
    await writeFile(path.join(repoDir, "file.txt"), "modified\n");
    await rm(path.join(repoDir, "file.txt"));

    const status = await streamGitStatus(repoDir);

    expect(status.staged).toContain("staged.txt");
    expect(status.created).toContain("staged.txt");
    expect(status.deleted).toContain("file.txt");
    expect(status.isClean).toBe(false);
  });

  it("truncates untracked entries when total cap is reached", async () => {
    repoDir = await setupRepo();
    await Promise.all(
      Array.from({ length: 25 }, (_, i) =>
        writeFile(path.join(repoDir, `top-${i}.txt`), "x"),
      ),
    );

    const status = await streamGitStatus(repoDir, {
      perDirUntrackedCap: 1000,
      totalUntrackedCap: 10,
    });

    expect(status.totalUntrackedTruncated).toBe(true);
    expect(status.untracked.length).toBe(10);
    expect(status.totalUntrackedSeen).toBe(25);
  });

  it("rejects when aborted", async () => {
    repoDir = await setupRepo();
    const controller = new AbortController();
    controller.abort();
    await expect(
      streamGitStatus(repoDir, { signal: controller.signal }),
    ).rejects.toThrow();
  });
});
