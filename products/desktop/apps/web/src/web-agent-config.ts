import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { getReasoningEffortOptions } from "@posthog/agent/adapters/reasoning-effort";
import {
  getAvailableCodexModes,
  getAvailableModes,
} from "@posthog/agent/execution-mode";
import {
  DEFAULT_CODEX_MODEL,
  DEFAULT_GATEWAY_MODEL,
  fetchGatewayModels,
  formatGatewayModelName,
  type GatewayModel,
  getClaudeModelRecency,
  isAnthropicModel,
  isCloudflareModel,
  isOpenAIModel,
} from "@posthog/agent/gateway-models";
import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import type { Adapter } from "@posthog/shared";

// Web port of AgentService.getPreviewConfigOptions (workspace-server). The
// desktop host runs this in the Node main process; the browser can run the exact
// same logic because it's a plain fetch to the PostHog LLM gateway (CORS-open,
// access-control-allow-origin: *) plus pure option-building. Kept here in the
// host so the web router stays a thin forward and packages/* are untouched.
export async function getWebPreviewConfigOptions(
  apiHost: string,
  adapter: Adapter = "claude",
): Promise<SessionConfigOption[]> {
  const gatewayUrl = getLlmGatewayUrl(apiHost);
  const gatewayModels = await fetchGatewayModels({ gatewayUrl });

  const modelFilter =
    adapter === "codex"
      ? isOpenAIModel
      : (model: GatewayModel) =>
          isAnthropicModel(model) || isCloudflareModel(model);

  const modelOptions = gatewayModels
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
      options: modelOptions,
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
