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
  reset: vi.fn(),
  /** Every mounted hook hears the host-wide GitHub callback. */
  onConnected: [] as Array<() => void>,
  projectHasTeamIntegration: undefined as boolean | null | undefined,
}));

const integrationState = vi.hoisted(() => ({
  hasGithubIntegration: false,
  isLoadingIntegrations: false,
}));

const installRequestState = vi.hoisted(() => ({
  results: [] as Array<Record<string, unknown>>,
  install_url: "https://github.com/apps/posthog/installations/new",
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
  useUserGithubIntegrations: () => ({ data: [], isSuccess: true }),
}));
vi.mock("@posthog/ui/features/integrations/useGithubInstallRequests", () => ({
  useGithubInstallRequests: () => ({ data: installRequestState }),
}));
vi.mock(
  "@posthog/ui/features/integrations/useDismissGithubInstallRequest",
  () => ({
    useDismissGithubInstallRequest: () => ({
      mutate: vi.fn(),
      isPending: false,
    }),
  }),
);
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
      reset: connectState.reset,
    };
  },
}));

function makeTask(id: string, state?: Record<string, unknown>): Task {
  return {
    id,
    task_number: 1,
    slug: id,
    title: "Blocked task",
    description: `Investigate ${id}`,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    origin_product: "user_created",
    ...(state
      ? { latest_run: { state } as NonNullable<Task["latest_run"]> }
      : {}),
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
    installRequestState.results = [];
  });

  it("shows the owner message with the install link while approval is pending", () => {
    installRequestState.results = [
      { id: "req-1", status: "pending", github_login: "octocat" },
    ];

    render(
      <GithubConnectionRequiredRecovery
        task={makeTask("task-1")}
        open
        onOpenChange={() => undefined}
      />,
    );

    expect(
      screen.getByText(/Open https:\/\/github\.com\/apps\/posthog/),
    ).toBeInTheDocument();
  });

  it("finishes the connection once an owner approves", () => {
    installRequestState.results = [
      {
        id: "req-1",
        status: "approved",
        installation_id: "42",
        account_login: "acme",
      },
    ];

    render(
      <GithubConnectionRequiredRecovery
        task={makeTask("task-1")}
        open
        onOpenChange={() => undefined}
      />,
    );

    fireEvent.click(screen.getByText("Finish connecting"));

    expect(connectState.connect).toHaveBeenCalledOnce();
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

  it("waits for an explicit retry after connecting", async () => {
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
      screen.getByText("GitHub is connected. Retry the task to continue."),
    ).toBeInTheDocument();

    const retryButton = document.querySelector<HTMLButtonElement>(
      '[data-attr="retry-github-blocked-task"]',
    );
    expect(retryButton).not.toBeNull();
    await act(async () => {
      fireEvent.click(retryButton as HTMLButtonElement);
    });

    expect(
      screen.getByText(
        "Only the person who created this task can send it messages.",
      ),
    ).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(retryButton as HTMLButtonElement);
    });

    expect(sessionService.retryGithubRequiredCloudRun).toHaveBeenCalledTimes(2);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("explains how to recover when GitHub cannot access the repository", async () => {
    sessionService.retryGithubRequiredCloudRun.mockRejectedValueOnce(
      new Error(
        "User-authored run requires a linked GitHub account with repo access.",
      ),
    );

    render(
      <GithubConnectionRequiredRecovery
        task={makeTask("task-1")}
        open
        onOpenChange={() => undefined}
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
    await act(async () => {
      fireEvent.click(
        document.querySelector(
          '[data-attr="retry-github-blocked-task"]',
        ) as HTMLButtonElement,
      );
    });

    expect(
      screen.getByText(
        "GitHub is connected, but it cannot access this repository. Update GitHub repository access, then try again.",
      ),
    ).toBeInTheDocument();
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

    fireEvent.click(
      document.querySelector(
        '[data-attr="retry-github-blocked-task"]',
      ) as HTMLButtonElement,
    );

    expect(
      sessionService.retryGithubRequiredCloudRun,
    ).toHaveBeenCalledExactlyOnceWith(
      "task-started",
      "Investigate task-started",
    );
  });

  it("offers a retry when the web host regains focus after connecting", () => {
    render(
      <GithubConnectionRequiredRecovery
        task={makeTask("task-1")}
        open
        onOpenChange={() => undefined}
      />,
    );

    fireEvent.click(
      document.querySelector(
        '[data-attr="connect-github-for-code-context"]',
      ) as HTMLButtonElement,
    );
    fireEvent.focus(window);

    expect(connectState.reset).toHaveBeenCalledOnce();
    expect(
      screen.getByText("GitHub is connected. Retry the task to continue."),
    ).toBeInTheDocument();
  });

  it("warns when the failed task had attachments", () => {
    render(
      <GithubConnectionRequiredRecovery
        task={makeTask("task-1", {
          pending_user_artifact_ids: ["attachment-1"],
        })}
        open
        onOpenChange={() => undefined}
      />,
    );

    expect(
      screen.getByText(
        "This restart does not include attachments from the failed task. Add them again after it starts.",
      ),
    ).toBeInTheDocument();
  });
});
