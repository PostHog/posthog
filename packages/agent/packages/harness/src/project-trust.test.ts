import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  createPiRuntimeTrustResolver,
  readPiProjectTrust,
  writePiProjectTrust,
} from "./project-trust";

const temporaryDirectories: string[] = [];

async function temporaryDirectory(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "posthog-pi-trust-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { force: true, recursive: true })),
  );
});

describe("Pi project trust", () => {
  it("persists trust for a repository and applies it to managed worktrees", async () => {
    const agentDir = await temporaryDirectory();
    const workspaceRoot = await temporaryDirectory();
    const repository = join(workspaceRoot, "repository");
    const worktree = join(workspaceRoot, "worktrees", "task-1");
    await mkdir(repository);
    await mkdir(join(worktree, ".pi", "extensions"), { recursive: true });

    expect(readPiProjectTrust(repository, worktree, agentDir)).toEqual({
      trusted: false,
      hasProjectResources: true,
    });

    writePiProjectTrust(repository, true, agentDir);

    expect(readPiProjectTrust(repository, worktree, agentDir)).toEqual({
      trusted: true,
      hasProjectResources: true,
    });
  });

  it("does not carry initial repository trust into an unrelated session cwd", async () => {
    const agentDir = await temporaryDirectory();
    const initialRepository = await temporaryDirectory();
    const unrelatedRepository = await temporaryDirectory();
    const resolveTrust = createPiRuntimeTrustResolver(
      initialRepository,
      true,
      agentDir,
    );

    expect(resolveTrust(initialRepository)).toBe(true);
    expect(resolveTrust(unrelatedRepository)).toBe(false);

    writePiProjectTrust(unrelatedRepository, true, agentDir);
    expect(resolveTrust(unrelatedRepository)).toBe(true);
  });

  it("honors Pi trust decisions inherited from an ancestor", async () => {
    const agentDir = await temporaryDirectory();
    const parent = await temporaryDirectory();
    const repository = join(parent, "repository");
    await mkdir(repository);

    writePiProjectTrust(parent, true, agentDir);

    expect(readPiProjectTrust(repository, repository, agentDir).trusted).toBe(
      true,
    );
  });
});
