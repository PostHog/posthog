import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  aiGatewayDenialCode,
  aiGatewayRemintReason,
  classifyGatewayLimitError,
} from "@posthog/shared";
import {
  buildPosthogProjectHeaderRecord,
  buildPosthogPropertiesHeaderRecord,
  buildPosthogPropertyHeaderRecord,
  type PosthogProperties,
} from "@posthog/shared/posthog-property-headers";
import { inject, injectable } from "inversify";
import type { AuthService } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";
import { AuthServiceEvent } from "../auth/schemas";
import type { GatewayTokenService } from "./gateway-token";
import {
  GATEWAY_TOKEN_SERVICE,
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
  type GatewayRoute,
  type LlmMessage,
  type PromptOutput,
  type UsageOutput,
  usageOutput,
} from "./schemas";

// Bounded helper workloads (titles, summaries, commit messages, PR copy) run on
// the cheapest model rather than the gateway default.
export const HELPER_GATEWAY_MODEL = "claude-haiku-4-5";

const FREE_TIER_GATEWAY_MODEL = "@cf/zai-org/glm-5.2";

type GoRoute = Extract<GatewayRoute, { mode: "go" }>;

export function desktopUsageUrl(apiHost: string, projectId: number): string {
  return `${apiHost}/api/projects/${projectId}/desktop/usage/`;
}

type SendOptions = {
  system?: string;
  maxTokens?: number;
  model: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  posthogProperties?: PosthogProperties;
};

// The Go gateway's model for a helper prompt, picked from the token's pin
// so a free-tier token never spends a round trip on a refused model.
function pickGoModel(route: GoRoute, requested: string): string {
  const allowed = route.allowedModels;
  if (allowed === null || allowed.includes(requested)) return requested;
  if (route.plan === "free" && allowed.includes(FREE_TIER_GATEWAY_MODEL)) {
    return FREE_TIER_GATEWAY_MODEL;
  }
  return allowed[0] ?? requested;
}

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
    @inject(GATEWAY_TOKEN_SERVICE)
    private readonly gatewayTokens: GatewayTokenService,
  ) {
    this.auth = host;
    this.endpoints = host;
    this.log = logger.scope("llm-gateway");
    this.authService = authService;
    let orgId = authService.getState().currentOrgId;
    authService.on(AuthServiceEvent.StateChanged, (state) => {
      if (state.currentOrgId === orgId) return;
      orgId = state.currentOrgId;
      this.lastKnownCodeUsageSubscribed = null;
      this.legacyUsageOrgs.clear();
    });
  }

  private readonly auth: LlmGatewayAuth;
  private readonly endpoints: LlmGatewayEndpoints;
  private readonly log: LlmGatewayLogger;
  private readonly authService: AuthService;

  private lastKnownCodeUsageSubscribed: boolean | null = null;
  // Orgs whose server has no Django usage endpoint yet (a 404 once).
  private readonly legacyUsageOrgs = new Set<string>();

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
    const route = await this.gatewayTokens
      .getRoute()
      .catch((): GatewayRoute => ({ mode: "legacy", reason: "route_failed" }));
    if (route.mode === "blocked") {
      throw new LlmGatewayError(
        route.detail,
        "billing_error",
        route.reason,
        402,
      );
    }
    if (route.mode === "go") {
      return this.sendGoPrompt(
        messages,
        {
          ...options,
          model: pickGoModel(route, requested),
        },
        route,
      );
    }
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

  private async sendGoPrompt(
    messages: LlmMessage[],
    options: SendOptions,
    route: GoRoute,
  ): Promise<PromptOutput> {
    const send = (current: GoRoute) =>
      this.executePrompt(
        messages,
        options,
        `${current.gatewayUrl}/v1/messages`,
        (url, init) =>
          (this.auth.fetch ?? fetch)(url, {
            ...init,
            redirect: "error",
            headers: {
              ...(init.headers as Record<string, string>),
              Authorization: `Bearer ${current.token}`,
            },
          }),
        buildPosthogPropertiesHeaderRecord({
          ...options.posthogProperties,
          ai_product: "posthog_code",
          team_id: current.teamId,
        }),
      );
    try {
      return await send(route);
    } catch (error) {
      const reason = remintReason(error);
      if (!reason) throw error;
      const fresh = await this.gatewayTokens
        .remint(reason, route.token, route.projectId)
        .catch(() => null);
      if (!fresh || fresh.mode !== "go") throw error;
      try {
        return await send(fresh);
      } catch (retryError) {
        if (
          reason === "unauthorized" &&
          remintReason(retryError) === "unauthorized"
        ) {
          this.gatewayTokens.fallBack(fresh.token, fresh.projectId);
        }
        throw retryError;
      }
    }
  }

  private async sendPrompt(
    messages: LlmMessage[],
    options: SendOptions,
  ): Promise<PromptOutput> {
    const auth = await this.auth.getValidAccessToken();
    return this.executePrompt(
      messages,
      options,
      this.endpoints.messagesUrl(auth.apiHost),
      (url, init) => this.auth.authenticatedFetch(url, init),
      {
        ...this.projectScopeHeaders(),
        ...(options.posthogProperties
          ? buildPosthogPropertyHeaderRecord(options.posthogProperties)
          : {}),
      },
    );
  }

  private async executePrompt(
    messages: LlmMessage[],
    options: SendOptions,
    messagesUrl: string,
    fetchImpl: (url: string, init: RequestInit) => Promise<Response>,
    extraHeaders: Record<string, string>,
  ): Promise<PromptOutput> {
    const { system, maxTokens, model, signal, timeoutMs = 60_000 } = options;

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
      ...extraHeaders,
    };

    let response: Response;
    try {
      response = await fetchImpl(messagesUrl, {
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
        (typeof errorData?.message === "string" ? errorData.message : "") ||
        detail ||
        `HTTP ${response.status}: ${response.statusText}`;
      const errorType = errorData?.error?.type || "unknown_error";
      const errorCode = aiGatewayDenialCode(
        response.headers.get("x-posthog-denial"),
        errorData,
      );

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
    const { currentOrgId, currentProjectId } = this.authService.getState();
    const useLegacy =
      currentProjectId === null ||
      (currentOrgId !== null && this.legacyUsageOrgs.has(currentOrgId));
    const usageUrl = useLegacy
      ? this.endpoints.legacyUsageUrl(auth.apiHost)
      : this.endpoints.usageUrl(auth.apiHost, currentProjectId);

    this.log.debug("Fetching usage", { url: usageUrl });

    let response: Response;
    try {
      response = await this.auth.authenticatedFetch(usageUrl, {
        headers: this.projectScopeHeaders(),
      });
      if (!useLegacy && response.status === 404) {
        if (currentOrgId !== null) this.legacyUsageOrgs.add(currentOrgId);
        response = await this.auth.authenticatedFetch(
          this.endpoints.legacyUsageUrl(auth.apiHost),
          { headers: this.projectScopeHeaders() },
        );
      }
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
    if (usage.ai_credits && !usage.ai_credits.exhausted) {
      this.gatewayTokens.clearBlocked();
    }
    if (usage.code_usage_subscribed !== undefined) {
      this.lastKnownCodeUsageSubscribed = usage.code_usage_subscribed;
    }
    return usage;
  }

  private projectScopeHeaders(): Record<string, string> {
    return buildPosthogProjectHeaderRecord(
      this.authService.getState().currentProjectId,
    );
  }
}

function remintReason(error: unknown) {
  if (!(error instanceof LlmGatewayError)) return null;
  return aiGatewayRemintReason(error.statusCode, error.code);
}
