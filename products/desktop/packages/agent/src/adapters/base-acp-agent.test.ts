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
});
