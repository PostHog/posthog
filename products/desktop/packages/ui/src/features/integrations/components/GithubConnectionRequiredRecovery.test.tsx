import type { Task } from "@posthog/shared/domain-types";
import { fireEvent, render } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GithubConnectionRequiredRecovery } from "./GithubConnectionRequiredRecovery";

const sessionService = vi.hoisted(() => ({
  retryGithubRequiredCloudRun: vi.fn().mockResolvedValue(undefined),
}));

const connectState = vi.hoisted(() => ({
  connect: vi.fn(async () => undefined),
  /** Every mounted hook hears the host-wide GitHub callback. */
  onConnected: [] as Array<() => void>,
}));

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol.for("test.session-service"),
}));
vi.mock("@posthog/di/react", () => ({ useService: () => sessionService }));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (selector: (state: unknown) => unknown) =>
    selector({ currentProjectId: 1, cloudRegion: "us" }),
}));
vi.mock("@posthog/ui/features/folders/useFolders", () => ({
  useFolders: () => ({ folders: [] }),
}));
vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useRepositoryIntegration: () => ({ hasGithubIntegration: false }),
}));
vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: false }),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput: vi.fn() }));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));
vi.mock("@posthog/ui/features/integrations/useGithubUserConnect", () => ({
  useGithubConnect: ({ onConnected }: { onConnected?: () => void }) => {
    if (onConnected) connectState.onConnected.push(onConnected);
    return {
      error: null,
      isConnecting: false,
      isTimedOut: false,
      hasError: false,
      isPending: false,
      connect: connectState.connect,
    };
  },
}));

function makeTask(id: string): Task {
  return {
    id,
    task_number: 1,
    slug: id,
    title: "Blocked task",
    description: `Investigate ${id}`,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    origin_product: "user_created",
  };
}

describe("GithubConnectionRequiredRecovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    connectState.onConnected = [];
  });

  it("retries only the task whose dialog started the connection", async () => {
    render(
      <>
        <GithubConnectionRequiredRecovery
          task={makeTask("task-started")}
          open
          onOpenChange={() => undefined}
        />
        <GithubConnectionRequiredRecovery
          task={makeTask("task-bystander")}
          open={false}
          onOpenChange={() => undefined}
        />
      </>,
    );

    const connectButton = document.querySelector<HTMLButtonElement>(
      '[data-attr="connect-github-for-code-context"]',
    );
    expect(connectButton).not.toBeNull();
    fireEvent.click(connectButton as HTMLButtonElement);
    expect(connectState.connect).toHaveBeenCalledOnce();

    expect(connectState.onConnected).toHaveLength(2);
    await act(async () => {
      for (const onConnected of connectState.onConnected) onConnected();
    });

    expect(
      sessionService.retryGithubRequiredCloudRun,
    ).toHaveBeenCalledExactlyOnceWith(
      "task-started",
      "Investigate task-started",
    );
  });
});
