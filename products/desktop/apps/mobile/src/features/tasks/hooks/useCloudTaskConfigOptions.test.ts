import {
  DEFAULT_GATEWAY_MODEL,
  type GatewayModel,
  GLM53_FLASH_MODEL_FLAG,
  GLM53_MODEL_FLAG,
  KIMI_MODEL_FLAG,
} from "@posthog/shared";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type PropsWithChildren } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockGetCloudTaskGatewayModels, mockUseAuthStore, mockUseFeatureFlag } =
  vi.hoisted(() => ({
    mockGetCloudTaskGatewayModels: vi.fn(),
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
    getCloudTaskGatewayModels: mockGetCloudTaskGatewayModels,
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

async function renderHook(
  adapter: "claude" | "codex" = "claude",
  currentValue?: string,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let currentResult: ReturnType<typeof useCloudTaskConfigOptions>;

  function HookProbe() {
    currentResult = useCloudTaskConfigOptions(adapter, currentValue);
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

function inferOwnedBy(id: string): string {
  if (id.startsWith("claude-") || id.startsWith("anthropic/"))
    return "anthropic";
  if (id.startsWith("gpt-") || id.startsWith("openai/")) return "openai";
  if (id.startsWith("@cf/")) return "cloudflare";
  if (id.startsWith("zai-org/") || id.includes("deepseek")) return "baseten";
  return id.split("/")[0] ?? "anthropic";
}

function gatewayModel(
  id: string,
  extra: Partial<GatewayModel> = {},
): GatewayModel {
  return {
    id,
    owned_by: inferOwnedBy(id),
    context_window: 200_000,
    supports_streaming: true,
    supports_vision: false,
    allowed: true,
    ...extra,
  };
}

describe("useCloudTaskConfigOptions", () => {
  beforeEach(() => {
    mockGetCloudTaskGatewayModels.mockReset();
    mockUseFeatureFlag.mockReset();
    mockUseFeatureFlag.mockReturnValue(false);
    mockUseAuthStore.mockImplementation((selector) =>
      selector({ oauthAccessToken: "token" }),
    );
  });

  it("builds per-adapter config options from the gateway models", async () => {
    mockGetCloudTaskGatewayModels.mockResolvedValue([
      gatewayModel("claude-sonnet-5"),
      gatewayModel("gpt-5.6-sol"),
    ]);

    const result = await renderHook("claude");
    await waitForAssertion(() => {
      const modelOption = getModelConfigOption(result.current.configOptions);
      expect(modelOption.options.map((o) => o.value)).toEqual([
        "claude-sonnet-5",
      ]);
      expect(result.current.hasLiveConfig).toBe(true);
    });
  });

  it("groups both harnesses' models by vendor for the cross-harness picker", async () => {
    mockGetCloudTaskGatewayModels.mockResolvedValue([
      gatewayModel("claude-sonnet-5"),
      gatewayModel("gpt-5.6-sol"),
    ]);

    const result = await renderHook("claude");
    await waitForAssertion(() => {
      const groups = result.current.modelGroups.map((g) => ({
        group: g.group,
        options: g.options.map((o) => o.value),
      }));
      expect(groups).toEqual([
        { group: "anthropic", options: ["claude-sonnet-5"] },
        { group: "openai", options: ["gpt-5.6-sol"] },
      ]);
    });
  });

  it("replaces a hidden GLM current model with a visible model", async () => {
    mockGetCloudTaskGatewayModels.mockResolvedValue([
      gatewayModel("zai-org/glm-5.3"),
      gatewayModel("claude-sonnet-5"),
    ]);

    const result = await renderHook("claude");
    await waitForAssertion(() => {
      const modelOption = getModelConfigOption(result.current.configOptions);
      expect(modelOption.options.map((option) => option.value)).toEqual([
        "claude-sonnet-5",
      ]);
      // Cross-harness groups drop the empty Z.ai group along with its heading.
      expect(result.current.modelGroups.map((g) => g.group)).not.toContain(
        "zai-org",
      );
    });
  });

  it.each([
    { enabledFlag: GLM53_MODEL_FLAG, model: "zai-org/glm-5.3" },
    { enabledFlag: GLM53_FLASH_MODEL_FLAG, model: "zai-org/glm-5.3-flash" },
  ])("gates $model independently", async ({ enabledFlag, model }) => {
    mockUseFeatureFlag.mockImplementation(
      (flag: string) => flag === enabledFlag,
    );
    mockGetCloudTaskGatewayModels.mockResolvedValue([
      gatewayModel("zai-org/glm-5.3"),
      gatewayModel("zai-org/glm-5.3-flash"),
    ]);

    const result = await renderHook("claude");
    await waitForAssertion(() => {
      const modelOption = getModelConfigOption(result.current.configOptions);
      expect(modelOption.options.map((option) => option.value)).toEqual([
        model,
      ]);
    });
  });

  it("keeps the shared fallback when unauthenticated", async () => {
    mockUseAuthStore.mockImplementation((selector) =>
      selector({ oauthAccessToken: null }),
    );

    const result = await renderHook("claude");

    expect(
      getModelConfigOption(result.current.configOptions).currentValue,
    ).toBe(DEFAULT_GATEWAY_MODEL);
    expect(mockGetCloudTaskGatewayModels).not.toHaveBeenCalled();
    expect(result.current.isConfigReady).toBe(true);
  });

  it("keeps a model missing from the catalog selectable via a synthetic entry", async () => {
    mockGetCloudTaskGatewayModels.mockResolvedValue([
      gatewayModel("claude-sonnet-5"),
    ]);

    // A gateway blip drops the running model; the picker must still list it so
    // the user can see what's selected instead of an empty highlight.
    const result = await renderHook("claude", "claude-fable-legacy");
    await waitForAssertion(() => {
      expect(
        result.current.modelGroups.some((group) =>
          group.options.some(
            (option) => option.value === "claude-fable-legacy",
          ),
        ),
      ).toBe(true);
    });
  });

  it("hides Kimi K3 when its flag is off and keeps it when on", async () => {
    mockGetCloudTaskGatewayModels.mockResolvedValue([
      gatewayModel("moonshotai/kimi-k3", { owned_by: "modal" }),
      gatewayModel("claude-sonnet-5"),
    ]);

    let flagOn = false;
    mockUseFeatureFlag.mockImplementation(
      (flag: string) => flag === KIMI_MODEL_FLAG && flagOn,
    );

    const off = await renderHook("claude");
    await waitForAssertion(() => {
      const values = getModelConfigOption(
        off.current.configOptions,
      ).options.map((option) => option.value);
      expect(values).not.toContain("moonshotai/kimi-k3");
    });

    flagOn = true;
    const on = await renderHook("claude");
    await waitForAssertion(() => {
      const values = getModelConfigOption(on.current.configOptions).options.map(
        (option) => option.value,
      );
      expect(values).toContain("moonshotai/kimi-k3");
    });
  });

  it("makes the shared fallback usable after the live catalog fails", async () => {
    mockGetCloudTaskGatewayModels.mockRejectedValue(new Error("offline"));

    const result = await renderHook("claude");
    await waitForAssertion(() => {
      expect(result.current.isConfigReady).toBe(true);
    });

    expect(
      getModelConfigOption(result.current.configOptions).currentValue,
    ).toBe(DEFAULT_GATEWAY_MODEL);
  });
});
