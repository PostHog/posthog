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
  it("briefs the agent to build the loop as a workflow", async () => {
    const input = await buildInputFor("Summarize open PRs");
    expect(input.customInstructions).toContain("`workflows-create`");
    expect(input.customInstructions).not.toContain("`loops-create`");
    expect(input.content).toBe("Summarize open PRs");
    expect(input.repository).toBeUndefined();
  });

  it("starts one task when a second submit lands while the first is still starting", async () => {
    let release = (): void => {};
    const run = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          release = () => resolve(true);
        }),
    );
    mockedRunner.mockImplementation(() => ({ run, isRunning: false }));

    const { result } = renderHook(() => useLoopBuilderTask());
    const first = result.current.runTask("Summarize open PRs");
    const second = result.current.runTask("Summarize open PRs");
    release();
    await Promise.all([first, second]);

    expect(run).toHaveBeenCalledTimes(1);
  });
});
