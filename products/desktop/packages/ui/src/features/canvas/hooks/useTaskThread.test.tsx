import type { TaskThreadMessage } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  createTaskThreadMessage: vi.fn(),
  sendTaskThreadMessageToAgent: vi.fn(),
}));
const mockTaskThreadService = vi.hoisted(() => ({
  postMessageToAgent: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));
vi.mock("@posthog/di/react", () => ({
  useService: () => mockTaskThreadService,
}));

import { usePostTaskThreadMessageToAgent } from "./useTaskThread";

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function message(overrides?: Partial<TaskThreadMessage>): TaskThreadMessage {
  return {
    id: "message-id",
    task: "task-id",
    content: "@agent investigate this",
    created_at: "2026-07-16T00:00:00Z",
    ...overrides,
  };
}

describe("usePostTaskThreadMessageToAgent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
  });

  it("posts an @agent message through the combined client operation", async () => {
    mockTaskThreadService.postMessageToAgent.mockResolvedValue({
      message: message({ forwarded_to_agent_at: "2026-07-16T00:00:01Z" }),
      sendError: null,
    });
    const { result } = renderHook(
      () => usePostTaskThreadMessageToAgent("task-id"),
      { wrapper },
    );

    await act(async () => {
      await result.current.postMessageToAgent("@agent investigate this");
    });

    expect(mockTaskThreadService.postMessageToAgent).toHaveBeenCalledWith(
      mockClient,
      "task-id",
      "@agent investigate this",
    );
  });

  it("returns a forwarding error after the message has been posted", async () => {
    const sendError = new Error("No active run");
    mockTaskThreadService.postMessageToAgent.mockResolvedValue({
      message: message(),
      sendError,
    });
    const { result } = renderHook(
      () => usePostTaskThreadMessageToAgent("task-id"),
      { wrapper },
    );

    let outcome: Awaited<
      ReturnType<typeof result.current.postMessageToAgent>
    > | null = null;
    await act(async () => {
      outcome = await result.current.postMessageToAgent(
        "@agent investigate this",
      );
    });

    expect(outcome).toEqual({ message: message(), sendError });
    expect(mockTaskThreadService.postMessageToAgent).toHaveBeenCalledTimes(1);
  });
});
