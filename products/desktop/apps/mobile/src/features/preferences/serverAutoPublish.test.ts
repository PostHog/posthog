import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockGetMyTaskRunConfig, mockSetMyTaskDefaults } = vi.hoisted(() => ({
  mockGetMyTaskRunConfig: vi.fn(),
  mockSetMyTaskDefaults: vi.fn(),
}));

vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({
    getMyTaskRunConfig: mockGetMyTaskRunConfig,
    setMyTaskDefaults: mockSetMyTaskDefaults,
  }),
}));

vi.mock("@/features/auth", () => ({
  useAuthStore: vi.fn(),
}));

import {
  pullAutoPublishCloudRuns,
  saveAutoPublishCloudRuns,
} from "./serverAutoPublish";
import { usePreferencesStore } from "./stores/preferencesStore";

const PROJECT_ID = 2;
const INITIAL_STATE = usePreferencesStore.getState();

function serverConfig(autoPublish: boolean | null) {
  return {
    taskDefaults: {
      start_in_plan_mode: null,
      auto_publish_cloud_runs: autoPublish,
    },
  };
}

beforeEach(() => {
  usePreferencesStore.setState(INITIAL_STATE, true);
  mockGetMyTaskRunConfig.mockReset();
  mockSetMyTaskDefaults.mockReset();
  mockSetMyTaskDefaults.mockResolvedValue(undefined);
});

describe("pullAutoPublishCloudRuns", () => {
  it.each([true, false])("adopts a server value of %s", async (value) => {
    usePreferencesStore.setState({ autoPublishCloudRuns: !value });
    mockGetMyTaskRunConfig.mockResolvedValue(serverConfig(value));

    await pullAutoPublishCloudRuns(PROJECT_ID);

    expect(usePreferencesStore.getState().autoPublishCloudRuns).toBe(value);
    expect(mockSetMyTaskDefaults).not.toHaveBeenCalled();
  });

  it("uploads the local value when the server has none", async () => {
    usePreferencesStore.setState({ autoPublishCloudRuns: false });
    mockGetMyTaskRunConfig.mockResolvedValue(serverConfig(null));

    await pullAutoPublishCloudRuns(PROJECT_ID);

    expect(mockSetMyTaskDefaults).toHaveBeenCalledWith(PROJECT_ID, {
      auto_publish_cloud_runs: false,
    });
    expect(usePreferencesStore.getState().autoPublishCloudRuns).toBe(false);
  });

  it("keeps a toggle made while the pull was in flight", async () => {
    let resolveConfig: (config: ReturnType<typeof serverConfig>) => void =
      () => {};
    mockGetMyTaskRunConfig.mockReturnValue(
      new Promise((resolve) => {
        resolveConfig = resolve;
      }),
    );

    const pull = pullAutoPublishCloudRuns(PROJECT_ID);
    await saveAutoPublishCloudRuns(PROJECT_ID, false);
    resolveConfig(serverConfig(true));
    await pull;

    expect(usePreferencesStore.getState().autoPublishCloudRuns).toBe(false);
  });
});

describe("saveAutoPublishCloudRuns", () => {
  it("saves the value locally and on the server", async () => {
    await saveAutoPublishCloudRuns(PROJECT_ID, false);

    expect(usePreferencesStore.getState().autoPublishCloudRuns).toBe(false);
    expect(mockSetMyTaskDefaults).toHaveBeenCalledWith(PROJECT_ID, {
      auto_publish_cloud_runs: false,
    });
  });

  it("restores the previous value when the server save fails", async () => {
    usePreferencesStore.setState({ autoPublishCloudRuns: true });
    mockSetMyTaskDefaults.mockRejectedValue(new Error("offline"));

    await expect(saveAutoPublishCloudRuns(PROJECT_ID, false)).rejects.toThrow(
      "offline",
    );

    expect(usePreferencesStore.getState().autoPublishCloudRuns).toBe(true);
  });

  it("sends overlapping saves in order", async () => {
    const sent: boolean[] = [];
    mockSetMyTaskDefaults.mockImplementation(
      async (
        _projectId: number,
        changes: { auto_publish_cloud_runs: boolean },
      ) => {
        await Promise.resolve();
        sent.push(changes.auto_publish_cloud_runs);
      },
    );

    await Promise.all([
      saveAutoPublishCloudRuns(PROJECT_ID, false),
      saveAutoPublishCloudRuns(PROJECT_ID, true),
      saveAutoPublishCloudRuns(PROJECT_ID, false),
    ]);

    expect(sent).toEqual([false, true, false]);
  });

  it("does not undo a newer toggle when an older save fails", async () => {
    usePreferencesStore.setState({ autoPublishCloudRuns: true });
    mockSetMyTaskDefaults
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(undefined);

    const first = saveAutoPublishCloudRuns(PROJECT_ID, false);
    const second = saveAutoPublishCloudRuns(PROJECT_ID, false);
    await expect(first).rejects.toThrow("offline");
    await second;

    expect(usePreferencesStore.getState().autoPublishCloudRuns).toBe(false);
  });
});
