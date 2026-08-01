import type { ReportModelResolver } from "@posthog/core/inbox/identifiers";
import type { Adapter } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import type { QueryClient } from "@tanstack/react-query";

const log = logger.scope("resolve-default-model");

/**
 * Resolve the model for the given adapter via the preview-config tRPC query.
 *
 * `preferredModel` (e.g. the persisted last-used model) is honoured only if the
 * gateway still offers it; otherwise the server default (`currentValue`) is
 * returned. Returns undefined if the call fails or the option is missing.
 *
 * Used by one-click flows that create cloud tasks directly (Discuss, Create PR,
 * scout chat) without going through TaskInput – they need a model to pass to the
 * saga. Validating the preferred model here is what keeps a stale persisted id
 * the gateway no longer offers from reaching the run and 403-ing.
 */
export async function resolveDefaultModel(
  queryClient: QueryClient,
  apiHost: string,
  adapter: Adapter,
  modelResolver: ReportModelResolver,
  preferredModel?: string | null,
): Promise<string | undefined> {
  void queryClient;
  try {
    return await modelResolver.resolveDefaultModel(
      apiHost,
      adapter,
      preferredModel,
    );
  } catch (error) {
    log.warn("Failed to resolve default model", { error, adapter });
  }
  return undefined;
}
