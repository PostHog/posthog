import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { getReasoningEffortOptions } from "@posthog/agent/adapters/reasoning-effort";
import {
  getAvailableCodexModes,
  getAvailableModes,
} from "@posthog/agent/execution-mode";
import {
  buildProviderModelGroups,
  type GatewayModelRow,
  gatewayModelRowsFromTaskModels,
  normalizeGatewayModelsResponse,
  TASK_MODELS_FETCH_TIMEOUT_MS,
  taskModelsUrl,
} from "@posthog/agent/gateway-models";
import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { resolveService } from "@posthog/di/container";
import { type Adapter, buildCloudTaskConfigOptions } from "@posthog/shared";

export async function fetchWebTaskModelRows(): Promise<GatewayModelRow[]> {
  const auth = resolveService<AuthService>(AUTH_SERVICE);
  const projectId = auth.getState().currentProjectId;
  if (projectId === null) return [];
  try {
    const { apiHost } = await auth.getValidAccessToken();
    const response = await auth.authenticatedFetch(
      fetch,
      taskModelsUrl(apiHost, projectId),
      { signal: AbortSignal.timeout(TASK_MODELS_FETCH_TIMEOUT_MS) },
    );
    if (!response.ok) return [];
    return gatewayModelRowsFromTaskModels(await response.json());
  } catch {
    return [];
  }
}

// Web port of AgentService.getPreviewConfigOptions (workspace-server). The
// desktop host runs this in the Node main process; the browser can run the exact
// same logic because it's an authenticated fetch of Django's tasks/models
// catalog plus pure option-building. Kept here in the
// host so the web router stays a thin forward and packages/* are untouched.
export async function getWebPreviewConfigOptions(
  adapter: Adapter = "claude",
  allHarnessModels = false,
): Promise<SessionConfigOption[]> {
  const gatewayModels = normalizeGatewayModelsResponse(
    await fetchWebTaskModelRows(),
  );
  const configOptions = buildCloudTaskConfigOptions(
    gatewayModels,
    adapter,
    adapter === "codex" ? getAvailableCodexModes() : getAvailableModes(),
  ) as SessionConfigOption[];

  const modelOption = configOptions.find(
    (option) => option.category === "model",
  );
  const resolvedModelId =
    modelOption?.type === "select" ? modelOption.currentValue : "";

  if (allHarnessModels && modelOption?.type === "select") {
    modelOption.options = buildProviderModelGroups(
      gatewayModels,
      adapter,
      resolvedModelId,
    );
  }

  const effortOption = configOptions.find(
    (option) => option.category === "thought_level",
  );
  const effortOpts = getReasoningEffortOptions(adapter, resolvedModelId);
  if (effortOption?.type === "select" && effortOpts) {
    effortOption.options = effortOpts;
  }

  return configOptions;
}
