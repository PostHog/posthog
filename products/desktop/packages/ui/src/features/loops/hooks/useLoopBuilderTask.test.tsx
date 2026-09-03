import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import { resolveFeatureFlagAfterLoad } from "@posthog/ui/features/feature-flags/useFeatureFlagsLoaded";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLoopBuilderTask } from "./useLoopBuilderTask";

vi.mock("@posthog/di/react", () => ({
  useService: () => ({}),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlagsLoaded", () => ({
  useFeatureFlagsLoaded: () => true,
  resolveFeatureFlagAfterLoad: vi.fn(),
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner", () => ({
  useInboxCloudTaskRunner: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: () => "us:1",
  useAuthStore: { getState: () => ({ authState: {} }) },
}));

const mockedResolveFlag = vi.mocked(resolveFeatureFlagAfterLoad);
const mockedRunner = vi.mocked(useInboxCloudTaskRunner);

const inputContext: InboxCloudTaskInputContext = {
  cloudRepository: null,
  githubUserIntegrationId: null,
  adapter: "claude",
  model: "model-1",
  reasoningLevel: "medium",
} as InboxCloudTaskInputContext;

/** Runs the hook and returns the task input its `buildInput` produces. */
async function buildInputFor(instructions: string): Promise<TaskCreationInput> {
  let built: TaskCreationInput | null = null;
  mockedRunner.mockImplementation((options) => ({
    run: async () => {
      built = options.buildInput(inputContext);
    },
    isRunning: false,
  }));
  const { result } = renderHook(() => useLoopBuilderTask());
  await result.current.runTask(instructions);
  if (!built) throw new Error("buildInput was not called");
  return built;
}

describe("useLoopBuilderTask", () => {
  beforeEach(() => {
    mockedResolveFlag.mockReset();
  });

  it.each([
    { flag: false, expects: "`loops-create`", forbids: "`workflows-create`" },
    { flag: true, expects: "`workflows-create`", forbids: "`loops-create`" },
  ])(
    "briefs the agent for the backend the flag selects (flag=$flag)",
    async ({ flag, expects, forbids }) => {
      mockedResolveFlag.mockResolvedValue(flag);
      const input = await buildInputFor("Summarize open PRs");
      expect(input.customInstructions).toContain(expects);
      expect(input.customInstructions).not.toContain(forbids);
      expect(input.content).toBe("Summarize open PRs");
      expect(input.repository).toBeUndefined();
    },
  );
});
