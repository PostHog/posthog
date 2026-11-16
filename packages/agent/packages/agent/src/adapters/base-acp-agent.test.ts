import type {
  AgentSideConnection,
  InitializeRequest,
  InitializeResponse,
  NewSessionRequest,
  NewSessionResponse,
  PromptRequest,
  PromptResponse,
} from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchGatewayModels } from "../gateway-models";
import { BaseAcpAgent } from "./base-acp-agent";

vi.mock("../gateway-models", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../gateway-models")>()),
  fetchGatewayModels: vi.fn(),
}));

class TestAcpAgent extends BaseAcpAgent {
  readonly adapterName = "claude";

  async initialize(_request: InitializeRequest): Promise<InitializeResponse> {
    throw new Error("Not implemented");
  }

  async newSession(_request: NewSessionRequest): Promise<NewSessionResponse> {
    throw new Error("Not implemented");
  }

  async prompt(_request: PromptRequest): Promise<PromptResponse> {
    throw new Error("Not implemented");
  }

  protected async interrupt(): Promise<void> {}
}

describe("BaseAcpAgent", () => {
  beforeEach(() => {
    vi.mocked(fetchGatewayModels).mockReset();
  });

  it("offers gateway-advertised Baseten models to Claude sessions", async () => {
    vi.mocked(fetchGatewayModels).mockResolvedValue([
      {
        id: "claude-opus-4-8",
        owned_by: "anthropic",
        context_window: 1_000_000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
      },
      {
        id: "deepseek-ai/deepseek-v4-flash-0731",
        owned_by: "baseten",
        context_window: 1_048_000,
        supports_streaming: true,
        supports_vision: false,
        allowed: true,
      },
    ]);

    const agent = new TestAcpAgent({} as AgentSideConnection);
    const result = await agent.getModelConfigOptions(
      "deepseek-ai/deepseek-v4-flash-0731",
      "https://gateway.us.posthog.com/posthog_code",
      "token",
    );

    expect(result.currentModelId).toBe("deepseek-ai/deepseek-v4-flash-0731");
    expect(result.options).toContainEqual(
      expect.objectContaining({
        value: "deepseek-ai/deepseek-v4-flash-0731",
        name: "DeepSeek V4 Flash",
      }),
    );
  });

  it.each(["zai-org/glm-5.3", "zai-org/glm-5.3-flash"])(
    "keeps gateway-owned served model %s selected for Claude sessions",
    async (requestedModel) => {
      vi.mocked(fetchGatewayModels).mockResolvedValue([
        {
          id: "claude-opus-4-8",
          owned_by: "anthropic",
          context_window: 1_000_000,
          supports_streaming: true,
          supports_vision: true,
          allowed: true,
        },
        {
          id: requestedModel,
          owned_by: "posthog",
          context_window: 200_000,
          supports_streaming: true,
          supports_vision: false,
          allowed: true,
          api_shapes: [
            "openai-chat-completions",
            "openai-responses",
            "anthropic-messages",
          ],
        },
      ]);

      const agent = new TestAcpAgent({} as AgentSideConnection);
      const result = await agent.getModelConfigOptions(
        requestedModel,
        "https://gateway.us.posthog.com/posthog_code",
        "token",
      );

      expect(result.currentModelId).toBe(requestedModel);
      expect(result.options).toContainEqual(
        expect.objectContaining({ value: requestedModel }),
      );
      expect(result.options).not.toContainEqual(
        expect.objectContaining({ description: "Custom model" }),
      );
    },
  );

  it("falls back when the gateway cannot serve the saved model on Messages", async () => {
    vi.mocked(fetchGatewayModels).mockResolvedValue([
      {
        id: "claude-opus-4-8",
        owned_by: "anthropic",
        context_window: 1_000_000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
        api_shapes: ["anthropic-messages", "openai-chat-completions"],
      },
      {
        id: "zai-org/glm-5.3",
        owned_by: "posthog",
        context_window: 200_000,
        supports_streaming: true,
        supports_vision: false,
        allowed: true,
        api_shapes: ["openai-chat-completions", "openai-responses"],
      },
    ]);

    const agent = new TestAcpAgent({} as AgentSideConnection);
    const result = await agent.getModelConfigOptions(
      "zai-org/glm-5.3",
      "https://gateway.us.posthog.com/posthog_code",
      "token",
    );

    expect(result.currentModelId).toBe("claude-opus-4-8");
    expect(result.options).not.toContainEqual(
      expect.objectContaining({ value: "zai-org/glm-5.3" }),
    );
  });

  it("falls back when the gateway lists the saved native model without Messages", async () => {
    vi.mocked(fetchGatewayModels).mockResolvedValue([
      {
        id: "claude-opus-4-8",
        owned_by: "anthropic",
        context_window: 1_000_000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
        api_shapes: ["anthropic-messages", "openai-chat-completions"],
      },
      {
        id: "claude-sonnet-5",
        owned_by: "anthropic",
        context_window: 1_000_000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
        api_shapes: ["openai-chat-completions"],
      },
    ]);

    const agent = new TestAcpAgent({} as AgentSideConnection);
    const result = await agent.getModelConfigOptions(
      "claude-sonnet-5",
      "https://gateway.us.posthog.com/posthog_code",
      "token",
    );

    expect(result.currentModelId).toBe("claude-opus-4-8");
    expect(result.options).not.toContainEqual(
      expect.objectContaining({ value: "claude-sonnet-5" }),
    );
  });

  it("keeps a saved native Anthropic id the gateway omits as a custom option", async () => {
    vi.mocked(fetchGatewayModels).mockResolvedValue([
      {
        id: "claude-opus-4-8",
        owned_by: "anthropic",
        context_window: 1_000_000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
      },
    ]);

    const agent = new TestAcpAgent({} as AgentSideConnection);
    const result = await agent.getModelConfigOptions(
      "anthropic/claude-sonnet-5",
      "https://gateway.us.posthog.com/posthog_code",
      "token",
    );

    expect(result.currentModelId).toBe("anthropic/claude-sonnet-5");
    expect(result.options).toContainEqual(
      expect.objectContaining({
        value: "anthropic/claude-sonnet-5",
        description: "Custom model",
      }),
    );
  });

  it.each([
    "moonshotai/kimi-k3",
    "deepseek-ai/deepseek-v4-flash-0731",
    "deepseek-ai/deepseek-v4.1-flash-1017-fast",
    "zai-org/glm-5.3",
    "zai-org/glm-5.3-flash",
  ])(
    "does not restore omitted gateway model %s as a custom option",
    async (savedModel) => {
      vi.mocked(fetchGatewayModels).mockResolvedValue([
        {
          id: "claude-opus-4-8",
          owned_by: "anthropic",
          context_window: 1_000_000,
          supports_streaming: true,
          supports_vision: true,
          allowed: true,
        },
      ]);

      const agent = new TestAcpAgent({} as AgentSideConnection);
      const warn = vi.spyOn(agent.logger, "warn");
      const result = await agent.getModelConfigOptions(
        savedModel,
        "https://gateway.us.posthog.com/posthog_code",
        "token",
      );

      expect(result.currentModelId).toBe("claude-opus-4-8");
      expect(result.options).not.toContainEqual(
        expect.objectContaining({ value: savedModel }),
      );
      expect(warn).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          requestedModel: savedModel,
          fallbackModel: "claude-opus-4-8",
        }),
      );
    },
  );
});
