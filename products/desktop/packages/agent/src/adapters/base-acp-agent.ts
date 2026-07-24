import type {
  Agent,
  AgentSideConnection,
  AuthenticateRequest,
  CancelNotification,
  InitializeRequest,
  InitializeResponse,
  NewSessionRequest,
  NewSessionResponse,
  PromptRequest,
  PromptResponse,
  ReadTextFileRequest,
  ReadTextFileResponse,
  SessionConfigSelectOption,
  SessionNotification,
  WriteTextFileRequest,
  WriteTextFileResponse,
} from "@agentclientprotocol/sdk";
import { restrictedModelMeta } from "@posthog/shared";
import {
  compareModelsForPicker,
  DEFAULT_GATEWAY_MODEL,
  fetchGatewayModels,
  formatGatewayModelName,
  type GatewayModel,
  isAnthropicModel,
  isCloudflareModel,
  isCloudflareModelId,
  pickAllowedModel,
} from "../gateway-models";
import { Logger } from "../utils/logger";
/**
 * Shared settings manager interface that both Claude's SettingsManager
 * and Codex's CodexSettingsManager implement. BaseAcpAgent only calls
 * dispose() on this; each adapter's Session type narrows it to the
 * concrete implementation.
 */
export interface BaseSettingsManager {
  dispose(): void;
  getCwd(): string;
  setCwd(cwd: string): Promise<void>;
  initialize(): Promise<void>;
}

export interface BaseSession {
  notificationHistory: SessionNotification[];
  cancelled: boolean;
  interruptReason?: string;
  abortController: AbortController;
  settingsManager: BaseSettingsManager;
}

const DEFAULT_CONTEXT_WINDOW = 200_000;

export abstract class BaseAcpAgent implements Agent {
  abstract readonly adapterName: string;
  protected session!: BaseSession;
  protected sessionId!: string;
  client: AgentSideConnection;
  logger: Logger;
  fileContentCache: { [key: string]: string } = {};
  protected gatewayModels: GatewayModel[] = [];

  constructor(client: AgentSideConnection) {
    this.client = client;
    this.logger = new Logger({ debug: true, prefix: "[BaseAcpAgent]" });
  }

  abstract initialize(request: InitializeRequest): Promise<InitializeResponse>;
  abstract newSession(params: NewSessionRequest): Promise<NewSessionResponse>;
  abstract prompt(params: PromptRequest): Promise<PromptResponse>;
  protected abstract interrupt(): Promise<void>;

  async cancel(params: CancelNotification): Promise<void> {
    if (this.sessionId !== params.sessionId) {
      throw new Error("Session ID mismatch");
    }
    this.session.cancelled = true;
    const meta = params._meta as { interruptReason?: string } | undefined;
    if (meta?.interruptReason) {
      this.session.interruptReason = meta.interruptReason;
    }
    await this.interrupt();
  }

  async closeSession(): Promise<void> {
    try {
      // Abort first so in-flight HTTP requests are cancelled,
      // otherwise interrupt() deadlocks waiting for the query to stop
      // while the query waits on an API call that will never abort.
      this.session.abortController.abort();
      await this.cancel({ sessionId: this.sessionId });
      this.session.settingsManager.dispose();
      this.logger.info("Closed session", { sessionId: this.sessionId });
    } catch (err) {
      this.logger.warn("Failed to close session", {
        sessionId: this.sessionId,
        error: err,
      });
    }
  }

  hasSession(sessionId: string): boolean {
    return this.sessionId === sessionId;
  }

  appendNotification(
    sessionId: string,
    notification: SessionNotification,
  ): void {
    if (this.sessionId === sessionId) {
      this.session.notificationHistory.push(notification);
    }
  }

  async readTextFile(
    params: ReadTextFileRequest,
  ): Promise<ReadTextFileResponse> {
    const response = await this.client.readTextFile(params);
    if (!params.limit && !params.line) {
      this.fileContentCache[params.path] = response.content;
    }
    return response;
  }

  async writeTextFile(
    params: WriteTextFileRequest,
  ): Promise<WriteTextFileResponse> {
    const response = await this.client.writeTextFile(params);
    this.fileContentCache[params.path] = params.content;
    return response;
  }

  async authenticate(_params: AuthenticateRequest): Promise<void> {
    throw new Error("Method not implemented.");
  }

  async getModelConfigOptions(
    currentModelOverride?: string,
    gatewayUrl?: string,
    gatewayAuthToken?: string,
  ): Promise<{
    currentModelId: string;
    options: SessionConfigSelectOption[];
  }> {
    // Authenticated so the gateway can mark plan-restricted models —
    // anonymous fetches see everything allowed.
    this.gatewayModels = await fetchGatewayModels(
      gatewayUrl ? { gatewayUrl, authToken: gatewayAuthToken } : undefined,
    );

    const adapterModels = this.gatewayModels
      // Cloudflare models are servable on the Claude adapter too — the gateway translates the
      // `@cf/` path onto its Anthropic-Messages surface — so include them alongside Anthropic models.
      .filter((model) => isAnthropicModel(model) || isCloudflareModel(model));

    const options = adapterModels
      .map((model) => ({
        value: model.id,
        name: formatGatewayModelName(model),
        description: `Context: ${model.context_window.toLocaleString()} tokens`,
        // Locked models stay listed so the picker can gate them instead of
        // silently dropping them.
        ...(model.allowed ? {} : { _meta: restrictedModelMeta() }),
      }))
      .sort((a, b) => compareModelsForPicker(a.value, b.value));

    // Models the Claude adapter can drive: Anthropic ids, plus Cloudflare `@cf/` ids the gateway
    // serves over its Anthropic-Messages surface. Anything else (e.g. a Codex/GPT id) is a genuine
    // adapter/model desync and falls back to the default.
    const isClaudeAdapterModelId = (modelId: string): boolean =>
      modelId.startsWith("claude-") ||
      modelId.startsWith("anthropic/") ||
      isCloudflareModelId(modelId);

    let currentModelId = currentModelOverride ?? DEFAULT_GATEWAY_MODEL;

    if (!options.some((opt) => opt.value === currentModelId)) {
      if (!isClaudeAdapterModelId(currentModelId)) {
        // A model the Claude adapter can't drive reached it, which means the adapter and model
        // desynced upstream (e.g. a Codex model paired with the Claude adapter). Log it instead of
        // silently masquerading as a deliberate Opus session.
        this.logger.warn(
          "Incompatible model requested on Claude adapter; falling back to default model",
          {
            requestedModel: currentModelId,
            fallbackModel: DEFAULT_GATEWAY_MODEL,
          },
        );
        currentModelId = DEFAULT_GATEWAY_MODEL;
      }
    }

    // Never auto-select a model the org's plan can't use — it would 403 on
    // the first message. An explicit user pick still goes through the
    // picker's upgrade gate.
    currentModelId = pickAllowedModel(adapterModels, currentModelId);

    if (!options.some((opt) => opt.value === currentModelId)) {
      options.unshift({
        value: currentModelId,
        name: currentModelId,
        description: "Custom model",
      });
    }

    return { currentModelId, options };
  }

  getContextWindowForModel(modelId: string): number {
    const match = this.gatewayModels.find((m) => m.id === modelId);
    return match?.context_window ?? DEFAULT_CONTEXT_WINDOW;
  }
}
