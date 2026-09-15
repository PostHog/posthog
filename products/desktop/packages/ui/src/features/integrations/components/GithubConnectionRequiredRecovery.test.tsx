import type { Task } from "@posthog/shared/domain-types";
import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GithubConnectionRequiredRecovery } from "./GithubConnectionRequiredRecovery";

const sessionService = vi.hoisted(() => ({
  retryGithubRequiredCloudRun: vi.fn(),
}));

const connectState = vi.hoisted(() => ({
  connect: vi.fn(async () => undefined),
  /** Every mounted hook hears the host-wide GitHub callback. */
  onConnected: [] as Array<() => void>,
  projectHasTeamIntegration: undefined as boolean | null | undefined,
}));

const integrationState = vi.hoisted(() => ({
  hasGithubIntegration: false,
  isLoadingIntegrations: false,
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
  useIntegrations: () => ({
    isPending: integrationState.isLoadingIntegrations,
  }),
}));
vi.mock("@posthog/ui/features/integrations/store", () => ({
  useIntegrationSelectors: () => ({
    hasGithubIntegration: integrationState.hasGithubIntegration,
  }),
}));
vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: false }),
}));
vi.mock("@posthog/ui/router/useOpenTask", () => ({ openTaskInput: vi.fn() }));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: { scope: () => ({ error: vi.fn(), info: vi.fn(), warn: vi.fn() }) },
}));
vi.mock("@posthog/ui/features/integrations/useGithubUserConnect", () => ({
  useGithubConnect: ({
    onConnected,
    projectHasTeamIntegration,
  }: {
    onConnected?: () => void;
    projectHasTeamIntegration: boolean | null;
  }) => {
    if (onConnected) connectState.onConnected.push(onConnected);
    connectState.projectHasTeamIntegration = projectHasTeamIntegration;
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
    sessionService.retryGithubRequiredCloudRun.mockResolvedValue(undefined);
    connectState.onConnected = [];
    connectState.projectHasTeamIntegration = undefined;
    integrationState.hasGithubIntegration = false;
    integrationState.isLoadingIntegrations = false;
  });

  it.each([
    {
      name: "holds the connect action while the integrations load",
      isLoadingIntegrations: true,
      disabled: true,
      projectHasTeamIntegration: null,
    },
    {
      name: "offers the connect action once the integrations land",
      isLoadingIntegrations: false,
      disabled: false,
      projectHasTeamIntegration: false,
    },
  ])(
    "$name",
    ({ isLoadingIntegrations, disabled, projectHasTeamIntegration }) => {
      integrationState.isLoadingIntegrations = isLoadingIntegrations;

      render(
        <GithubConnectionRequiredRecovery
          task={makeTask("task-1")}
          open
          onOpenChange={() => undefined}
        />,
      );

      const connectButton = document.querySelector<HTMLButtonElement>(
        '[data-attr="connect-github-for-code-context"]',
      );
      expect(connectButton?.getAttribute("aria-disabled")).toBe(
        disabled ? "true" : "false",
      );
      fireEvent.click(connectButton as HTMLButtonElement);
      expect(connectState.connect).toHaveBeenCalledTimes(disabled ? 0 : 1);
      expect(connectState.projectHasTeamIntegration).toBe(
        projectHasTeamIntegration,
      );
    },
  );

  it("offers a direct retry after a restart fails", async () => {
    sessionService.retryGithubRequiredCloudRun
      .mockRejectedValueOnce(
        new Error(
          "Only the person who created this task can send it messages.",
        ),
      )
      .mockResolvedValueOnce(undefined);
    const onOpenChange = vi.fn();

    render(
      <GithubConnectionRequiredRecovery
        task={makeTask("task-1")}
        open
        onOpenChange={onOpenChange}
      />,
    );

    fireEvent.click(
      document.querySelector(
        '[data-attr="connect-github-for-code-context"]',
      ) as HTMLButtonElement,
    );
    await act(async () => {
      for (const onConnected of connectState.onConnected) onConnected();
    });

    expect(onOpenChange).not.toHaveBeenCalled();
    expect(
      screen.getByText(
        "Only the person who created this task can send it messages.",
      ),
    ).toBeInTheDocument();

    const retryButton = document.querySelector<HTMLButtonElement>(
      '[data-attr="retry-github-blocked-task"]',
    );
    expect(retryButton).not.toBeNull();
    await act(async () => {
      fireEvent.click(retryButton as HTMLButtonElement);
    });

    expect(sessionService.retryGithubRequiredCloudRun).toHaveBeenCalledTimes(2);
    expect(onOpenChange).toHaveBeenCalledWith(false);
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
