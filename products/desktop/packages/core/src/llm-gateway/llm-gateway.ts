import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { classifyGatewayLimitError } from "@posthog/shared";
import {
  buildPosthogPropertyHeaderRecord,
  type PosthogProperties,
} from "@posthog/shared/posthog-property-headers";
import { inject, injectable } from "inversify";
import type { AuthService } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";
import { AuthServiceEvent } from "../auth/schemas";
import {
  LLM_GATEWAY_HOST,
  type LlmGatewayAuth,
  type LlmGatewayEndpoints,
  type LlmGatewayHost,
  type LlmGatewayLogger,
} from "./identifiers";
import {
  type AnthropicErrorResponse,
  type AnthropicMessagesRequest,
  type AnthropicMessagesResponse,
  type LlmMessage,
  type PromptOutput,
  type UsageOutput,
  usageOutput,
} from "./schemas";

// Bounded helper workloads (titles, summaries, commit messages, PR copy) run on
// the cheapest model rather than the gateway default.
export const HELPER_GATEWAY_MODEL = "claude-haiku-4-5";

export const FREE_TIER_GATEWAY_MODEL = "@cf/zai-org/glm-5.2";

export class LlmGatewayError extends Error {
  constructor(
    message: string,
    public readonly type: string,
    public readonly code?: string,
    public readonly statusCode?: number,
  ) {
    super(message);
    this.name = "LlmGatewayError";
  }
}

@injectable()
export class LlmGatewayService {
  constructor(
    @inject(LLM_GATEWAY_HOST)
    host: LlmGatewayHost,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
    @inject(AUTH_SERVICE)
    authService: AuthService,
  ) {
    this.auth = host;
    this.endpoints = host;
    this.log = logger.scope("llm-gateway");
    let orgId = authService.getState().currentOrgId;
    authService.on(AuthServiceEvent.StateChanged, (state) => {
      if (state.currentOrgId === orgId) return;
      orgId = state.currentOrgId;
      this.lastKnownCodeUsageSubscribed = null;
    });
  }

  private readonly auth: LlmGatewayAuth;
  private readonly endpoints: LlmGatewayEndpoints;
  private readonly log: LlmGatewayLogger;

  private lastKnownCodeUsageSubscribed: boolean | null = null;

  async prompt(
    messages: LlmMessage[],
    options: {
      system?: string;
      maxTokens?: number;
      model?: string;
      signal?: AbortSignal;
      timeoutMs?: number;
      /**
       * Free-form metadata forwarded as `x-posthog-property-<key>` headers.
       * The gateway lifts each one onto the `$ai_generation` event it
       * captures, so helper callers (commit messages, PR descriptions, etc.)
       * can be told apart from the agent's main generations.
       */
      posthogProperties?: PosthogProperties;
    } = {},
  ): Promise<PromptOutput> {
    const requested = options.model ?? this.endpoints.defaultModel;
    const model =
      this.lastKnownCodeUsageSubscribed === false
        ? FREE_TIER_GATEWAY_MODEL
        : requested;
    try {
      return await this.sendPrompt(messages, { ...options, model });
    } catch (error) {
      const isModelGate =
        error instanceof LlmGatewayError &&
        error.statusCode === 403 &&
        classifyGatewayLimitError(error.message) === "model_gate";
      if (!isModelGate || model === FREE_TIER_GATEWAY_MODEL) throw error;
      this.lastKnownCodeUsageSubscribed = false;
      this.log.warn("Model gated for free tier, retrying on free-tier model", {
        model,
        fallbackModel: FREE_TIER_GATEWAY_MODEL,
      });
      return await this.sendPrompt(messages, {
        ...options,
        model: FREE_TIER_GATEWAY_MODEL,
      });
    }
  }

  private async sendPrompt(
    messages: LlmMessage[],
    options: {
      system?: string;
      maxTokens?: number;
      model: string;
      signal?: AbortSignal;
      timeoutMs?: number;
      posthogProperties?: PosthogProperties;
    },
  ): Promise<PromptOutput> {
    const {
      system,
      maxTokens,
      model,
      signal,
      timeoutMs = 60_000,
      posthogProperties,
    } = options;

    const auth = await this.auth.getValidAccessToken();
    const messagesUrl = this.endpoints.messagesUrl(auth.apiHost);

    const requestBody: AnthropicMessagesRequest = {
      model,
      messages: messages.map((m) => ({ role: m.role, content: m.content })),
      stream: false,
    };

    if (maxTokens !== undefined) {
      requestBody.max_tokens = maxTokens;
    }

    if (system) {
      requestBody.system = system;
    }

    this.log.debug("Sending request to LLM gateway", {
      url: messagesUrl,
      model,
      messageCount: messages.length,
    });

    const timeoutController = new AbortController();
    const timeoutId = setTimeout(() => {
      timeoutController.abort();
    }, timeoutMs);
    const onCallerAbort = () => timeoutController.abort();
    if (signal) {
      if (signal.aborted) timeoutController.abort();
      else signal.addEventListener("abort", onCallerAbort, { once: true });
    }

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(posthogProperties
        ? buildPosthogPropertyHeaderRecord(posthogProperties)
        : {}),
    };

    let response: Response;
    try {
      response = await this.auth.authenticatedFetch(messagesUrl, {
        method: "POST",
        headers,
        body: JSON.stringify(requestBody),
        signal: timeoutController.signal,
      });
    } catch (err) {
      if (timeoutController.signal.aborted && !signal?.aborted) {
        throw new LlmGatewayError(
          `LLM gateway request timed out after ${timeoutMs}ms`,
          "timeout",
        );
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
      signal?.removeEventListener("abort", onCallerAbort);
    }

    if (!response.ok) {
      const errorBody = await response.text();
      let errorData: AnthropicErrorResponse | null = null;

      try {
        errorData = JSON.parse(errorBody) as AnthropicErrorResponse;
      } catch {
        this.log.error("Failed to parse error response", {
          errorBody,
          status: response.status,
        });
      }

      const detail =
        typeof errorData?.detail === "string" ? errorData.detail : undefined;
      const errorMessage =
        errorData?.error?.message ||
        detail ||
        `HTTP ${response.status}: ${response.statusText}`;
      const errorType = errorData?.error?.type || "unknown_error";
      const errorCode = errorData?.error?.code;

      this.log.error("LLM gateway request failed", {
        status: response.status,
        errorType,
        errorMessage,
      });

      throw new LlmGatewayError(
        errorMessage,
        errorType,
        errorCode,
        response.status,
      );
    }

    const data = (await response.json()) as AnthropicMessagesResponse;

    const textContent = data.content.find((c) => c.type === "text");
    const content = textContent?.text || "";

    this.log.debug("LLM gateway response received", {
      model: data.model,
      stopReason: data.stop_reason,
      inputTokens: data.usage.input_tokens,
      outputTokens: data.usage.output_tokens,
    });

    return {
      content,
      model: data.model,
      stopReason: data.stop_reason,
      usage: {
        inputTokens: data.usage.input_tokens,
        outputTokens: data.usage.output_tokens,
      },
    };
  }

  async fetchUsage(): Promise<UsageOutput> {
    const auth = await this.auth.getValidAccessToken();
    const usageUrl = this.endpoints.usageUrl(auth.apiHost);

    this.log.debug("Fetching usage from gateway", { url: usageUrl });

    let response: Response;
    try {
      response = await this.auth.authenticatedFetch(usageUrl);
    } catch (err) {
      this.log.warn("Usage fetch network error", {
        error: err instanceof Error ? err.message : String(err),
      });
      throw err;
    }

    if (!response.ok) {
      this.log.warn("Usage fetch failed", { status: response.status });
      throw new LlmGatewayError(
        `Failed to fetch usage: HTTP ${response.status}`,
        "usage_error",
        undefined,
        response.status,
      );
    }

    const usage = usageOutput.parse(await response.json());
    if (usage.code_usage_subscribed !== undefined) {
      this.lastKnownCodeUsageSubscribed = usage.code_usage_subscribed;
    }
    return usage;
  }
}
