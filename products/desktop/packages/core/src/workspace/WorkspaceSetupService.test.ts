import type { RootLogger } from "@posthog/di/logger";
import { describe, expect, it, vi } from "vitest";
import type { WorkspaceSetupGitClient } from "./identifiers";
import type { DetectedRepoFullName } from "./repoMismatch";
import { WorkspaceSetupService } from "./WorkspaceSetupService";

function makeLogger(): RootLogger {
  const scoped = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
  return { ...scoped, scope: vi.fn(() => scoped) };
}

function makeService(
  detectRepo: WorkspaceSetupGitClient["detectRepo"],
): WorkspaceSetupService {
  const git: WorkspaceSetupGitClient = { detectRepo };
  return new WorkspaceSetupService(git, makeLogger());
}

const detected: DetectedRepoFullName = {
  organization: "PostHog",
  repository: "posthog",
};

describe("WorkspaceSetupService.evaluateFolderSelection", () => {
  it("proceeds when task has no linked repository", async () => {
    const detectRepo = vi.fn();
    const service = makeService(detectRepo);

    const result = await service.evaluateFolderSelection(null, "/some/path");

    expect(result).toEqual({ kind: "proceed" });
    expect(detectRepo).not.toHaveBeenCalled();
  });

  it("proceeds when detected repo matches the linked repository", async () => {
    const service = makeService(vi.fn().mockResolvedValue(detected));

    const result = await service.evaluateFolderSelection(
      "posthog/POSTHOG",
      "/repo",
    );

    expect(result).toEqual({ kind: "proceed" });
  });

  it("flags a mismatch when detected repo differs", async () => {
    const service = makeService(vi.fn().mockResolvedValue(detected));

    const result = await service.evaluateFolderSelection(
      "PostHog/other",
      "/repo",
    );

    expect(result).toEqual({
      kind: "mismatch",
      detectedRepo: "PostHog/posthog",
    });
  });

  it("proceeds when no repo could be detected", async () => {
    const service = makeService(vi.fn().mockResolvedValue(null));

    const result = await service.evaluateFolderSelection(
      "PostHog/posthog",
      "/repo",
    );

    expect(result).toEqual({ kind: "proceed" });
  });

  it("proceeds when detection throws", async () => {
    const service = makeService(vi.fn().mockRejectedValue(new Error("boom")));

    const result = await service.evaluateFolderSelection(
      "PostHog/posthog",
      "/repo",
    );

    expect(result).toEqual({ kind: "proceed" });
  });
});
