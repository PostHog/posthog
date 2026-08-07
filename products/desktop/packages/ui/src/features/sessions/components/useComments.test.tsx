import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createResourceComment = vi.hoisted(() => vi.fn());

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ createResourceComment }),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: vi.fn(),
  useAuthStateValue: () => "user-1",
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

import { commentsForTarget, useCreateComment } from "./useComments";

const target = { scope: "task_artifact", itemId: "artifact-1" } as const;
const queryKey = ["comments", "user-1", "task-1"];

function comment(overrides: Partial<ResourceComment>): ResourceComment {
  return {
    id: "comment-1",
    created_by: null,
    content: "Existing comment",
    created_at: "2026-01-01T00:00:00Z",
    item_id: "artifact-1",
    item_context: { taskId: "task-1", anchor: { kind: "document" } },
    scope: "task_artifact",
    source_comment: null,
    completed_at: null,
    ...overrides,
  } as ResourceComment;
}

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("task comment cache", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        mutations: { retry: false },
        queries: { retry: false },
      },
    });
  });

  it("filters shared comments by both scope and item ID", () => {
    const matching = comment({});
    const sibling = comment({ id: "comment-2", item_id: "artifact-2" });
    const otherScope = comment({ id: "comment-3", scope: "desktop_canvas" });

    expect(commentsForTarget([matching, sibling, otherScope], target)).toEqual([
      matching,
    ]);
  });

  it("appends, replaces, and rolls back optimistic comments in the task cache", async () => {
    const existing = comment({});
    queryClient.setQueryData(queryKey, [existing]);
    let saveComment: (comment: ResourceComment) => void = () => undefined;
    createResourceComment.mockReturnValueOnce(
      new Promise<ResourceComment>((resolve) => {
        saveComment = resolve;
      }),
    );
    const { result } = renderHook(() => useCreateComment(target, "task-1"), {
      wrapper,
    });

    let createPromise!: Promise<ResourceComment>;
    act(() => {
      createPromise = result.current.mutateAsync({
        content: "New comment",
        context: { anchor: { kind: "document" } },
      });
    });
    await waitFor(() => {
      expect(
        queryClient.getQueryData<ResourceComment[]>(queryKey)?.at(-1)?.id,
      ).toMatch(/^optimistic-/);
    });

    const saved = comment({ id: "saved-comment", content: "New comment" });
    await act(async () => {
      saveComment(saved);
      await createPromise;
    });
    expect(queryClient.getQueryData(queryKey)).toEqual([existing, saved]);

    queryClient.setQueryData(queryKey, [existing]);
    createResourceComment.mockRejectedValueOnce(new Error("unavailable"));
    await act(async () => {
      await result.current
        .mutateAsync({
          content: "Failed comment",
          context: { anchor: { kind: "document" } },
        })
        .catch(() => undefined);
    });
    expect(queryClient.getQueryData(queryKey)).toEqual([existing]);
  });
});
