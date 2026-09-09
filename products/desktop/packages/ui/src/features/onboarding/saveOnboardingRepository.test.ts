import type { TaskChannel } from "@posthog/shared/domain-types";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { saveOnboardingRepository } from "./saveOnboardingRepository";

function channel(overrides: Partial<TaskChannel>): TaskChannel {
  return {
    id: "channel-id",
    name: "channel",
    channel_type: "public",
    starred: false,
    created_at: "2026-01-01T00:00:00Z",
    system_role: null,
    ...overrides,
  };
}

describe("saveOnboardingRepository", () => {
  it("updates empty system spaces and their shared cache", async () => {
    const personal = channel({
      id: "personal-id",
      name: "me",
      channel_type: "personal",
      system_role: "personal",
    });
    const general = channel({
      id: "general-id",
      name: "general",
      system_role: "general",
    });
    const updatedChannels = [personal, general].map((item) => ({
      ...item,
      github_integration: 12,
      repositories: ["posthog/posthog"],
    }));
    const updateTaskChannelRepositories = vi
      .fn()
      .mockImplementation((channelId: string) =>
        Promise.resolve(updatedChannels.find((item) => item.id === channelId)),
      );
    const client = {
      getIntegrations: vi.fn().mockResolvedValue([
        {
          id: 12,
          kind: "github",
          config: { account: { name: "PostHog" } },
        },
      ]),
      updateTaskChannelRepositories,
    };
    const queryClient = new QueryClient();

    await expect(
      saveOnboardingRepository({
        client,
        provisioned: {
          channels: [personal, general],
          personal_created: true,
          general_created: true,
        },
        queryClient,
        repository: "posthog/posthog",
      }),
    ).resolves.toBe(2);

    expect(updateTaskChannelRepositories).toHaveBeenCalledTimes(2);
    expect(updateTaskChannelRepositories).toHaveBeenCalledWith(
      "personal-id",
      12,
      ["posthog/posthog"],
    );
    expect(updateTaskChannelRepositories).toHaveBeenCalledWith(
      "general-id",
      12,
      ["posthog/posthog"],
    );
    expect(
      queryClient.getQueryData<TaskChannel[]>(TASK_CHANNELS_QUERY_KEY),
    ).toEqual(updatedChannels);
  });

  it("keeps the provisioned cache when no team integration matches", async () => {
    const general = channel({
      id: "general-id",
      name: "general",
      system_role: "general",
    });
    const client = {
      getIntegrations: vi.fn().mockResolvedValue([]),
      updateTaskChannelRepositories: vi.fn(),
    };
    const queryClient = new QueryClient();

    await expect(
      saveOnboardingRepository({
        client,
        provisioned: {
          channels: [general],
          personal_created: false,
          general_created: true,
        },
        queryClient,
        repository: "posthog/posthog",
      }),
    ).resolves.toBe(0);

    expect(client.updateTaskChannelRepositories).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(TASK_CHANNELS_QUERY_KEY)).toEqual([
      general,
    ]);
  });
});
