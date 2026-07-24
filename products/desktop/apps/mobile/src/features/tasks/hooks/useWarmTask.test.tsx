import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { mockWarmTask } = vi.hoisted(() => ({ mockWarmTask: vi.fn() }));
const flagState = vi.hoisted(() => ({ enabled: true as boolean }));

vi.mock("posthog-react-native", () => ({
  useFeatureFlag: () => flagState.enabled,
}));
vi.mock("@/features/tasks/api", () => ({
  warmTask: mockWarmTask,
}));
vi.mock("@/lib/logger", () => {
  const mockLogger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    scope: () => mockLogger,
  };
  return { logger: mockLogger };
});

import { useWarmTask } from "./useWarmTask";

interface Props {
  repository?: string | null;
  githubIntegrationId?: number | null;
  branch?: string | null;
  composerIsEmpty: boolean;
  runtimeAdapter?: string | null;
  model?: string | null;
  reasoningEffort?: string | null;
  sandboxEnvironmentId?: string | null;
  customImageId?: string | null;
}

const composing: Props = {
  repository: "acme/repo",
  githubIntegrationId: 42,
  branch: "main",
  composerIsEmpty: false,
};

const NULL_RUNTIME = {
  runtime_adapter: null,
  model: null,
  reasoning_effort: null,
};

function render(initial: Props) {
  let current = initial;
  function Wrapper() {
    useWarmTask(current);
    return null;
  }
  let renderer: ReactTestRenderer | null = null;
  act(() => {
    renderer = create(createElement(Wrapper));
  });
  return {
    rerender: (next: Props) => {
      current = next;
      act(() => {
        renderer?.update(createElement(Wrapper));
      });
    },
  };
}

async function flushDebounce(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
}

describe("useWarmTask", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    flagState.enabled = true;
    mockWarmTask.mockResolvedValue({ task_id: "task-1", run_id: "run-1" });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("fires a debounced warm when repo selected + composing", async () => {
    render(composing);
    expect(mockWarmTask).not.toHaveBeenCalled();

    await flushDebounce();

    expect(mockWarmTask).toHaveBeenCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
    });
  });

  it.each<{ name: string; props?: Partial<Props>; flagEnabled?: boolean }>([
    { name: "the flag is off", flagEnabled: false },
    { name: "no repository is selected", props: { repository: null } },
    { name: "no github integration", props: { githubIntegrationId: null } },
    { name: "the composer is empty", props: { composerIsEmpty: true } },
  ])("does not fire when $name", async ({ props, flagEnabled }) => {
    if (flagEnabled === false) {
      flagState.enabled = false;
    }
    render({ ...composing, ...props });
    await flushDebounce();
    expect(mockWarmTask).not.toHaveBeenCalled();
  });

  it("fires once the composer becomes non-empty", async () => {
    const { rerender } = render({ ...composing, composerIsEmpty: true });
    await flushDebounce();
    expect(mockWarmTask).not.toHaveBeenCalled();

    rerender(composing);
    await flushDebounce();
    expect(mockWarmTask).toHaveBeenCalledOnce();
  });

  it("does not re-fire for the same key after the composer empties and refills", async () => {
    const { rerender } = render(composing);
    await flushDebounce();
    expect(mockWarmTask).toHaveBeenCalledOnce();

    // Toggling `composerIsEmpty` flips `eligible` (a dep), so the effect
    // re-runs with the same key — the `lastWarmedKeyRef` guard, not React's
    // bail-out, is what blocks a second warm.
    rerender({ ...composing, composerIsEmpty: true });
    await flushDebounce();
    rerender({ ...composing, composerIsEmpty: false });
    await flushDebounce();
    expect(mockWarmTask).toHaveBeenCalledOnce();
  });

  it.each<{
    name: string;
    initial?: Partial<Props>;
    change: Partial<Props>;
    expected: Record<string, unknown>;
  }>([
    {
      name: "repository",
      change: { repository: "acme/other" },
      expected: {
        repository: "acme/other",
        github_integration: 42,
        branch: "main",
        ...NULL_RUNTIME,
      },
    },
    {
      name: "branch",
      change: { branch: "feature/x" },
      expected: {
        repository: "acme/repo",
        github_integration: 42,
        branch: "feature/x",
        ...NULL_RUNTIME,
      },
    },
    {
      name: "model",
      initial: {
        runtimeAdapter: "claude",
        model: "claude-opus-4-8",
        reasoningEffort: "high",
      },
      change: { model: "claude-sonnet-4-6" },
      expected: {
        repository: "acme/repo",
        github_integration: 42,
        branch: "main",
        runtime_adapter: "claude",
        model: "claude-sonnet-4-6",
        reasoning_effort: "high",
      },
    },
  ])(
    "warms the new selection when the $name changes",
    async ({ initial, change, expected }) => {
      const base = { ...composing, ...initial };
      const { rerender } = render(base);
      await flushDebounce();
      expect(mockWarmTask).toHaveBeenCalledOnce();

      rerender({ ...base, ...change });
      await flushDebounce();

      expect(mockWarmTask).toHaveBeenLastCalledWith(expected);
      expect(mockWarmTask).toHaveBeenCalledTimes(2);
    },
  );

  it("forwards the sandbox environment and custom image", async () => {
    render({
      ...composing,
      sandboxEnvironmentId: "environment-123",
      customImageId: "image-123",
    });
    await flushDebounce();

    expect(mockWarmTask).toHaveBeenCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
      sandbox_environment_id: "environment-123",
      custom_image_id: "image-123",
    });
  });

  it("re-warms when the custom image changes", async () => {
    const { rerender } = render({ ...composing, customImageId: "image-123" });
    await flushDebounce();
    expect(mockWarmTask).toHaveBeenCalledOnce();

    rerender({ ...composing, customImageId: "image-456" });
    await flushDebounce();

    expect(mockWarmTask).toHaveBeenCalledTimes(2);
    expect(mockWarmTask).toHaveBeenLastCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
      custom_image_id: "image-456",
    });
  });

  it("warms again for a new selection after a failed warm", async () => {
    mockWarmTask.mockRejectedValueOnce(new Error("boom"));
    const { rerender } = render(composing);
    await flushDebounce();
    expect(mockWarmTask).toHaveBeenCalledOnce();

    rerender({ ...composing, branch: "feature/x" });
    await flushDebounce();
    expect(mockWarmTask).toHaveBeenCalledTimes(2);
  });

  it("swallows warm errors without throwing", async () => {
    mockWarmTask.mockRejectedValue(new Error("boom"));
    render(composing);

    await expect(flushDebounce()).resolves.not.toThrow();
    expect(mockWarmTask).toHaveBeenCalledOnce();
  });
});
