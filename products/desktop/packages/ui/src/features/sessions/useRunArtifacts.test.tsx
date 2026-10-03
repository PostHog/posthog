import { SESSION_SERVICE } from "@posthog/core/sessions/sessionService";
import { ServiceProvider } from "@posthog/di/react";
import type { TaskRunArtifact } from "@posthog/shared";
import { useAuthStore } from "@posthog/ui/features/auth/store";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { useRunArtifacts } from "@posthog/ui/features/sessions/useRunArtifacts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { Container } from "inversify";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

const TASK_ID = "task-1";
const RUN_ID = "run-1";

function artifact(name: string): TaskRunArtifact {
  return { id: name, name, type: "output" } as TaskRunArtifact;
}

/** One event per finished upload, which is what re-keys the query. */
function uploadEvents(count: number) {
  return Array.from({ length: count }).flatMap((_, index) => [
    {
      type: "acp_message" as const,
      ts: index * 2,
      message: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call",
            toolCallId: `call-${index}`,
            _meta: {
              posthog: {
                toolName: "mcp__posthog-code-tools__upload_artifact",
              },
            },
          },
        },
      },
    },
    {
      type: "acp_message" as const,
      ts: index * 2 + 1,
      message: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call_update",
            toolCallId: `call-${index}`,
            status: "completed",
          },
        },
      },
    },
  ]);
}

function setUploads(count: number) {
  useSessionStore.setState({
    taskIdIndex: { [TASK_ID]: RUN_ID },
    sessions: {
      [RUN_ID]: { taskRunId: RUN_ID, events: uploadEvents(count) },
    },
    // biome-ignore lint/suspicious/noExplicitAny: the store's full shape isn't needed to drive this hook
  } as any);
}

// Built once: a wrapper that rebuilds these per render restarts the query on
// every render and never resolves.
const container = new Container();
container.bind(SESSION_SERVICE).toConstantValue({
  getCloudRunArtifacts: async () => [artifact("report.csv")],
});
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function wrapper({ children }: { children: ReactNode }) {
  return (
    <ServiceProvider container={container}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ServiceProvider>
  );
}

describe("useRunArtifacts", () => {
  beforeEach(() => {
    useAuthStore.setState({
      authState: {
        status: "authenticated",
        cloudRegion: "us",
        bootstrapComplete: true,
        // biome-ignore lint/suspicious/noExplicitAny: only the identity fields matter here
      } as any,
    });
    setUploads(0);
  });

  // A finished upload re-keys the query, which lands every caller on a cache
  // entry with nothing in it. Without carrying the last answer over, every
  // artifact already drawn in the transcript blinks back to unresolved on each
  // upload, which is what a person sees as a flicker.
  it("keeps the manifest on screen while a new upload re-keys the query", async () => {
    const { result, rerender } = renderHook(
      () => useRunArtifacts(TASK_ID, RUN_ID, { staleTime: 0 }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toHaveLength(1));

    setUploads(1);
    rerender();

    expect(result.current.data).toHaveLength(1);
    expect(result.current.isLoading).toBe(false);
  });
});
