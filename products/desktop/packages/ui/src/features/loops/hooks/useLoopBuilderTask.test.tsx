import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useLoopBuilderTask } from "./useLoopBuilderTask";

vi.mock("@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner", () => ({
  useInboxCloudTaskRunner: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: () => "us:1",
  useAuthStore: { getState: () => ({ authState: {} }) },
}));

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
      return true;
    },
    isRunning: false,
  }));
  const { result } = renderHook(() => useLoopBuilderTask());
  await result.current.runTask(instructions);
  if (!built) throw new Error("buildInput was not called");
  return built;
}

describe("useLoopBuilderTask", () => {
  it("briefs the agent for the workflows tools and runs repo-less", async () => {
    const input = await buildInputFor("Summarize open PRs");
    expect(input.customInstructions).toContain("`workflows-create`");
    expect(input.content).toBe("Summarize open PRs");
    expect(input.repository).toBeUndefined();
  });
});
