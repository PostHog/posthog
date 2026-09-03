import type { TaskChannel } from "@posthog/shared/domain-types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  enabled: true,
  integrations: {
    data: undefined as { id: number; kind: string }[] | undefined,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  },
  update: {
    isPending: false,
    error: null as Error | null,
    mutate: vi.fn(),
  },
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => mocks.enabled,
}));
vi.mock("@posthog/ui/features/integrations/useIntegrations", () => ({
  useIntegrations: () => mocks.integrations,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useUpdateTaskChannelSlackTaskRouting: () => mocks.update,
}));
vi.mock(
  "@posthog/ui/features/settings/components/SlackWorkspaceChannelPicker",
  () => ({
    SlackWorkspaceChannelPicker: ({
      channelValue,
      disabled,
    }: {
      channelValue: string | null;
      disabled: boolean;
    }) => (
      <button type="button" aria-label="Slack task channel" disabled={disabled}>
        {channelValue ?? "No Slack channel"}
      </button>
    ),
  }),
);

import { SpaceSlackTaskRouting } from "./SpaceSlackTaskRouting";

function taskChannel(overrides: Partial<TaskChannel> = {}): TaskChannel {
  return {
    id: "channel-1",
    name: "engineering",
    channel_type: "public",
    starred: false,
    created_at: "2026-09-03T00:00:00Z",
    ...overrides,
  };
}

describe("SpaceSlackTaskRouting", () => {
  beforeEach(() => {
    mocks.enabled = true;
    mocks.integrations.data = [];
    mocks.integrations.isPending = false;
    mocks.integrations.isError = false;
    mocks.integrations.refetch.mockReset();
    mocks.update.isPending = false;
    mocks.update.error = null;
    mocks.update.mutate.mockReset();
  });

  it("does not render when the feature flag is off", () => {
    mocks.enabled = false;

    render(<SpaceSlackTaskRouting channel={taskChannel()} />);

    expect(screen.queryByText("Slack task channel")).not.toBeInTheDocument();
  });

  it("shows the current channel but disables updates without routing permission", () => {
    mocks.integrations.data = [{ id: 1, kind: "slack" }];

    render(
      <SpaceSlackTaskRouting
        channel={taskChannel({
          can_manage_slack_task_routing: false,
          slack_task_routing: {
            integration: 1,
            slack_channel_id: "C123",
            display_name: "task-updates",
          },
        })}
      />,
    );

    expect(screen.getByText("C123|#task-updates")).toBeInTheDocument();
    expect(
      screen.getByText("A project admin must change this setting."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Slack task channel" }),
    ).toBeDisabled();
  });

  it("does not explain an unresolved routing permission", () => {
    mocks.integrations.data = [{ id: 1, kind: "slack" }];

    render(<SpaceSlackTaskRouting channel={taskChannel()} />);

    expect(
      screen.queryByText("A project admin must change this setting."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Slack task channel" }),
    ).toBeDisabled();
  });

  it("does not show the connect state while integrations load", () => {
    mocks.integrations.data = undefined;
    mocks.integrations.isPending = true;

    render(<SpaceSlackTaskRouting channel={taskChannel()} />);

    expect(screen.getByText("Loading Slack connections.")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Connect Slack in Settings to route new Slack tasks here.",
      ),
    ).not.toBeInTheDocument();
  });

  it("retries a failed integrations query", async () => {
    const user = userEvent.setup();
    mocks.integrations.isError = true;

    render(<SpaceSlackTaskRouting channel={taskChannel()} />);

    expect(
      screen.getByText("Couldn't load Slack connections."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(mocks.integrations.refetch).toHaveBeenCalledOnce();
  });
});
