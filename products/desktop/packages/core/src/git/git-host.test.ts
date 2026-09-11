import type { RootLogger } from "@posthog/di/logger";
import { describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import type { GitPrService } from "../git-pr/git-pr";
import type { CreatePrHost, CreatePrInput } from "../git-pr/identifiers";
import { GitHostService } from "./git-host";
import type { GitWorkspaceLookup, HostGitWorkspaceClient } from "./host-git";

const logger: RootLogger = {
  debug: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  scope: () => logger,
};

describe("GitHostService.createPr", () => {
  it.each([
    ["us", "task-1", "https://us.posthog.com/code/task/task-1"],
    ["eu", "task-2", "https://eu.posthog.com/code/task/task-2"],
    [null, "task-1", undefined],
    ["us", undefined, undefined],
  ] as const)(
    "passes task attribution for %s and %s",
    async (cloudRegion, taskId, taskUrl) => {
      const createPrViaGh = vi.fn().mockResolvedValue({
        success: true,
        message: "Created",
        prUrl: "https://github.com/example/repo/pull/1",
      });
      const workspace = {
        git: { createPrViaGh: { mutate: createPrViaGh } },
      } as unknown as HostGitWorkspaceClient;
      const prService = {
        createPr: (input: CreatePrInput, host: CreatePrHost) =>
          host.createPrViaGh(
            input.directoryPath,
            input.prTitle,
            input.prBody,
            input.draft,
          ),
      } as unknown as GitPrService;
      const auth = {
        getState: () => ({ cloudRegion }),
      } as unknown as AuthService;
      const service = new GitHostService(
        workspace,
        prService,
        { getSessionEnvForTask: vi.fn().mockResolvedValue({}) },
        {} as GitWorkspaceLookup,
        logger,
        auth,
      );

      await service.createPr({
        directoryPath: "/repo",
        flowId: "flow-1",
        taskId,
        prTitle: "Fix a bug",
        prBody: "Description",
        draft: true,
      });

      expect(createPrViaGh).toHaveBeenCalledWith({
        directoryPath: "/repo",
        title: "Fix a bug",
        body: "Description",
        draft: true,
        env: undefined,
        taskUrl,
      });
    },
  );
});
