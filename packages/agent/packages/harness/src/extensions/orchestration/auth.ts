/** Resolves the model and credentials for an isolated in-memory child session. */
import {
  type Api,
  InMemoryCredentialStore,
  type Model,
} from "@earendil-works/pi-ai";
import {
  type ExtensionContext,
  ModelRuntime,
} from "@earendil-works/pi-coding-agent";

export interface ResolvedModelAuth {
  model: Model<Api>;
  apiKey: string;
  headers?: Record<string, string>;
}

export class SubagentAuthError extends Error {}

export interface ModelRequest {
  /** Name used only for error messages (e.g. the requesting agent's name). */
  requestedBy: string;
  /** "provider/id", a bare model id, or `undefined` to use the parent's current model. */
  model?: string;
}

/**
 * Picks the model the child should use — `request.model` ("provider/id")
 * when set, otherwise the parent's current model — and resolves its
 * credentials via `ctx.modelRegistry`. Never performs a login/refresh
 * network call itself; `ctx.modelRegistry` already owns that for the parent
 * session.
 */
export async function resolveModelAuth(
  ctx: ExtensionContext,
  request: ModelRequest,
): Promise<ResolvedModelAuth> {
  let model: Model<Api> | undefined = ctx.model;

  if (request.model) {
    const slash = request.model.indexOf("/");
    model =
      slash > 0
        ? ctx.modelRegistry.find(
            request.model.slice(0, slash),
            request.model.slice(slash + 1),
          )
        : ctx.modelRegistry
            .getAll()
            .find(
              (candidate) =>
                candidate.id === request.model &&
                (!ctx.model || candidate.provider === ctx.model.provider),
            );

    if (!model) {
      throw new SubagentAuthError(
        `Unknown model "${request.model}" requested by "${request.requestedBy}".`,
      );
    }
  }

  if (!model) {
    throw new SubagentAuthError(
      "No active model to delegate to. Select a model first (/model).",
    );
  }

  const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
  if (!auth.ok || !auth.apiKey) {
    throw new SubagentAuthError(
      `No credentials available for model "${model.provider}/${model.id}".`,
    );
  }

  const headers: Record<string, string> = {};
  for (const [name, value] of Object.entries(auth.headers ?? {})) {
    if (value === null) {
      throw new SubagentAuthError(
        `The model "${model.provider}/${model.id}" uses provider headers that cannot be delegated safely. Choose another model for the subagent.`,
      );
    }
    headers[name] = value;
  }

  return {
    model,
    apiKey: auth.apiKey,
    ...(Object.keys(headers).length > 0 ? { headers } : {}),
  };
}

/**
 * Tries `primary`, then each of `fallbacks` in order, resolving to the first
 * model with usable credentials. If every explicit candidate fails and
 * `primary` named a specific model (e.g. a bundled agent pinned to a model
 * that doesn't exist under the parent's current provider), makes one
 * last attempt with no model at all — i.e. "inherit" the parent's current
 * model — before giving up. This is what lets an agent declare `model:
 * gpt-5.6-sol` and still run somewhere that model isn't available,
 * rather than hard-failing the whole subagent. Throws the last error if
 * nothing resolves.
 *
 * Careful with a `provider/id` primary here: `resolveModelAuth`'s slash
 * branch matches on the literal provider name, and this codebase registers
 * every model (Anthropic, OpenAI, Cloudflare alike) under one gateway
 * provider (`posthog`), not per-vendor providers — so `anthropic/<id>` will
 * never match and will always silently fall through to this inherit path.
 * Use the bare id (matched against `ctx.model.provider`) instead, as
 * `bundled-agents/Explore.md` does.
 */
export async function resolveModelAuthWithFallback(
  ctx: ExtensionContext,
  requestedBy: string,
  primary: string | undefined,
  fallbacks: string[] = [],
): Promise<ResolvedModelAuth> {
  const candidates = [primary, ...fallbacks];
  if (primary !== undefined) candidates.push(undefined);

  let lastError: unknown;
  for (const model of candidates) {
    try {
      return await resolveModelAuth(ctx, { requestedBy, model });
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new SubagentAuthError("No model could be resolved.");
}

export interface SubagentModelRuntime {
  model: Model<Api>;
  modelRuntime: ModelRuntime;
}

export async function createSubagentModelRuntime(
  auth: ResolvedModelAuth,
): Promise<SubagentModelRuntime> {
  const credentials = new InMemoryCredentialStore();
  const modelRuntime = await ModelRuntime.create({
    credentials,
    modelsPath: null,
    refreshOnCreate: false,
  });
  const { model, apiKey, headers } = auth;

  modelRuntime.registerProvider(model.provider, {
    baseUrl: model.baseUrl,
    api: model.api,
    apiKey,
    headers,
    models: [
      {
        id: model.id,
        name: model.name,
        api: model.api,
        baseUrl: model.baseUrl,
        reasoning: model.reasoning,
        thinkingLevelMap: model.thinkingLevelMap,
        input: model.input,
        cost: model.cost,
        contextWindow: model.contextWindow,
        maxTokens: model.maxTokens,
        headers: model.headers,
        compat: model.compat,
      },
    ],
  });
  await modelRuntime.setRuntimeApiKey(model.provider, apiKey);

  const childModel = modelRuntime.getModel(model.provider, model.id);
  if (!childModel) {
    throw new SubagentAuthError(
      `Model "${model.provider}/${model.id}" was not registered for the subagent.`,
    );
  }

  return { model: childModel, modelRuntime };
}
