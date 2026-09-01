import {
  type CloudTaskConfigOption,
  DEFAULT_GATEWAY_MODEL,
  GLM53_FLASH_MODEL_FLAG,
  GLM53_MODEL_FLAG,
} from "@posthog/shared";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type PropsWithChildren } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockGetCloudTaskConfigOptions, mockUseAuthStore, mockUseFeatureFlag } =
  vi.hoisted(() => ({
    mockGetCloudTaskConfigOptions: vi.fn(),
    mockUseAuthStore: vi.fn(),
    mockUseFeatureFlag: vi.fn(),
  }));

vi.mock("posthog-react-native", () => ({
  useFeatureFlag: mockUseFeatureFlag,
}));

vi.mock("@/features/auth", () => ({
  useAuthStore: mockUseAuthStore,
}));

vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({
    getCloudTaskConfigOptions: mockGetCloudTaskConfigOptions,
  }),
}));

import { getModelConfigOption } from "../composer/options";
import { useCloudTaskConfigOptions } from "./useCloudTaskConfigOptions";

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      children,
    );
  };
}

async function renderHook() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let currentResult: ReturnType<typeof useCloudTaskConfigOptions>;

  function HookProbe() {
    currentResult = useCloudTaskConfigOptions("claude");
    return null;
  }

  const Wrapper = createWrapper(queryClient);
  await act(async () => {
    create(createElement(Wrapper, null, createElement(HookProbe)));
    await Promise.resolve();
  });

  return {
    get current() {
      return currentResult;
    },
  };
}

async function waitForAssertion(assertion: () => void): Promise<void> {
  const timeoutAt = Date.now() + 2_000;
  while (Date.now() < timeoutAt) {
    try {
      assertion();
      return;
    } catch (error) {
      await new Promise((resolve) => setTimeout(resolve, 10));
      if (Date.now() >= timeoutAt) throw error;
    }
  }
}

describe("useCloudTaskConfigOptions", () => {
  beforeEach(() => {
    mockGetCloudTaskConfigOptions.mockReset();
    mockUseFeatureFlag.mockReset();
    mockUseFeatureFlag.mockReturnValue(false);
    mockUseAuthStore.mockImplementation((selector) =>
      selector({ oauthAccessToken: "token" }),
    );
  });

  it("uses the authenticated live Claude catalog", async () => {
    const liveOptions: CloudTaskConfigOption[] = [
      {
        id: "model",
        name: "Model",
        type: "select",
        currentValue: "claude-sonnet-5",
        options: [{ value: "claude-sonnet-5", name: "Claude Sonnet 5" }],
        category: "model",
        description: "Choose a model",
      },
    ];
    mockGetCloudTaskConfigOptions.mockResolvedValue(liveOptions);

    const result = await renderHook();
    await waitForAssertion(() => {
      expect(result.current.configOptions).toEqual(liveOptions);
      expect(result.current.hasLiveConfig).toBe(true);
    });
    expect(mockGetCloudTaskConfigOptions).toHaveBeenCalledWith("claude");
  });

  it("replaces a hidden GLM current model with a visible model", async () => {
    mockGetCloudTaskConfigOptions.mockResolvedValue([
      {
        id: "model",
        name: "Model",
        type: "select",
        currentValue: "@cf/zai-org/glm-5.2",
        options: [
          { value: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
          { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
        ],
        category: "model",
        description: "Choose a model",
      },
    ] satisfies CloudTaskConfigOption[]);

    const result = await renderHook();
    await waitForAssertion(() => {
      const modelOption = getModelConfigOption(result.current.configOptions);
      expect(modelOption.currentValue).toBe("claude-sonnet-5");
      expect(modelOption.options.map((option) => option.value)).toEqual([
        "claude-sonnet-5",
      ]);
    });
  });

  it.each([
    { enabledFlag: GLM53_MODEL_FLAG, model: "zai-org/glm-5.3" },
    { enabledFlag: GLM53_FLASH_MODEL_FLAG, model: "zai-org/glm-5.3-flash" },
  ])("gates $model independently", async ({ enabledFlag, model }) => {
    mockUseFeatureFlag.mockImplementation(
      (flag: string) => flag === enabledFlag,
    );
    mockGetCloudTaskConfigOptions.mockResolvedValue([
      {
        id: "model",
        name: "Model",
        type: "select",
        currentValue: model,
        options: [
          { value: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
          { value: "zai-org/glm-5.3", name: "GLM-5.3" },
          { value: "zai-org/glm-5.3-flash", name: "GLM-5.3 Flash" },
        ],
        category: "model",
        description: "Choose a model",
      },
    ] satisfies CloudTaskConfigOption[]);

    const result = await renderHook();
    await waitForAssertion(() => {
      const modelOption = getModelConfigOption(result.current.configOptions);
      expect(modelOption.currentValue).toBe(model);
      expect(modelOption.options.map((option) => option.value)).toEqual([
        model,
      ]);
    });
  });

  it("keeps the shared fallback when unauthenticated", async () => {
    mockUseAuthStore.mockImplementation((selector) =>
      selector({ oauthAccessToken: null }),
    );

    const result = await renderHook();

    expect(
      getModelConfigOption(result.current.configOptions).currentValue,
    ).toBe(DEFAULT_GATEWAY_MODEL);
    expect(mockGetCloudTaskConfigOptions).not.toHaveBeenCalled();
    expect(result.current.isConfigReady).toBe(true);
  });

  it("makes the shared fallback usable after the live catalog fails", async () => {
    mockGetCloudTaskConfigOptions.mockRejectedValue(new Error("offline"));

    const result = await renderHook();
    await waitForAssertion(() => {
      expect(result.current.isConfigReady).toBe(true);
    });

    expect(
      getModelConfigOption(result.current.configOptions).currentValue,
    ).toBe(DEFAULT_GATEWAY_MODEL);
  });
});
