import type {
  SessionConfigOption,
  SessionConfigSelectOption,
} from "@agentclientprotocol/sdk";
import { getReasoningEffortOptions } from "@posthog/agent/adapters/reasoning-effort";
import {
  getAvailableCodexModes,
  getAvailableModes,
} from "@posthog/agent/execution-mode";
import {
  buildProviderModelGroups,
  DEFAULT_CODEX_MODEL,
  DEFAULT_GATEWAY_MODEL,
  formatGatewayModelName,
  type GatewayModelRow,
  gatewayModelRowsFromTaskModels,
  getClaudeModelRecency,
  isClaudeAdapterModel,
  isCodexAdapterModel,
  normalizeGatewayModelsResponse,
  taskModelsUrl,
} from "@posthog/agent/gateway-models";
import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { resolveService } from "@posthog/di/container";
import { type Adapter, customModelMeta } from "@posthog/shared";

export async function fetchWebTaskModelRows(): Promise<GatewayModelRow[]> {
  const auth = resolveService<AuthService>(AUTH_SERVICE);
  const projectId = auth.getState().currentProjectId;
  if (projectId === null) return [];
  try {
    const { apiHost } = await auth.getValidAccessToken();
    const response = await auth.authenticatedFetch(
      fetch,
      taskModelsUrl(apiHost, projectId),
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

  const modelFilter =
    adapter === "codex" ? isCodexAdapterModel : isClaudeAdapterModel;

  const modelOptions: SessionConfigSelectOption[] = gatewayModels
    .filter((model) => modelFilter(model))
    .map((model) => ({
      value: model.id,
      name: formatGatewayModelName(model),
      description: `Context: ${model.context_window.toLocaleString()} tokens`,
    }));

  if (adapter === "claude") {
    modelOptions.sort(
      (a, b) => getClaudeModelRecency(a.value) - getClaudeModelRecency(b.value),
    );
  }

  const defaultModel =
    adapter === "codex"
      ? (modelOptions.find((o) => o.value === DEFAULT_CODEX_MODEL)?.value ??
        modelOptions[0]?.value ??
        "")
      : DEFAULT_GATEWAY_MODEL;

  const resolvedModelId = modelOptions.some((o) => o.value === defaultModel)
    ? defaultModel
    : (modelOptions[0]?.value ?? defaultModel);

  if (!modelOptions.some((o) => o.value === resolvedModelId)) {
    modelOptions.unshift({
      value: resolvedModelId,
      name: resolvedModelId,
      description: "Custom model",
      _meta: customModelMeta(),
    });
  }

  const modes =
    adapter === "codex" ? getAvailableCodexModes() : getAvailableModes();
  const modeOptions = modes.map((mode) => ({
    value: mode.id,
    name: mode.name,
    description: mode.description ?? undefined,
  }));
  const defaultMode = adapter === "codex" ? "auto" : "plan";

  const configOptions: SessionConfigOption[] = [
    {
      id: "mode",
      name: "Approval Preset",
      type: "select",
      currentValue: defaultMode,
      options: modeOptions,
      category: "mode",
      description: "Choose an approval and sandboxing preset for your session",
    },
    {
      id: "model",
      name: "Model",
      type: "select",
      currentValue: resolvedModelId,
      options: allHarnessModels
        ? buildProviderModelGroups(gatewayModels, adapter, resolvedModelId)
        : modelOptions,
      category: "model",
      description: "Choose which model Claude should use",
    },
  ];

  const effortOpts = getReasoningEffortOptions(adapter, resolvedModelId);
  if (effortOpts) {
    configOptions.push({
      id: adapter === "codex" ? "reasoning_effort" : "effort",
      name: adapter === "codex" ? "Reasoning Level" : "Effort",
      type: "select",
      currentValue: "high",
      options: effortOpts,
      category: "thought_level",
      description:
        adapter === "codex"
          ? "Controls how much reasoning effort the model uses"
          : "Controls how much effort Claude puts into its response",
    });
  }

  return configOptions;
}
