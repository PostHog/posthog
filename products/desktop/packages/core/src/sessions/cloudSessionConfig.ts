import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import type { Adapter, StoredLogEntry } from "@posthog/shared";
import { getAvailableCodexModes, getAvailableModes } from "./executionModes";

/**
 * Pure derivations of cloud session config options. No store or host access —
 * just shaping the config-option list the mode switcher renders.
 */

/**
 * Pull the most recent `config_option_update` payload out of a run's stored log
 * entries, so a reconnecting cloud session restores its last known options.
 */
export function extractLatestConfigOptionsFromEntries(
  entries: StoredLogEntry[],
): SessionConfigOption[] | undefined {
  let latest: SessionConfigOption[] | undefined;
  for (const entry of entries) {
    if (
      entry.type !== "notification" ||
      entry.notification?.method !== "session/update"
    ) {
      continue;
    }
    const params = entry.notification.params as
      | {
          update?: {
            sessionUpdate?: string;
            configOptions?: SessionConfigOption[];
          };
        }
      | undefined;
    if (
      params?.update?.sessionUpdate === "config_option_update" &&
      params.update.configOptions
    ) {
      latest = params.update.configOptions;
    }
  }
  return latest;
}

/**
 * Build default configOptions for cloud sessions so the mode switcher is
 * available in the UI even without a local agent connection.
 *
 * The `extra` options (model, thought_level) come from the preview-config trpc
 * query, which is async. Callers populate them after the session exists.
 */
export function buildCloudDefaultConfigOptions(
  initialMode: string | undefined,
  adapter: Adapter = "claude",
  extra: SessionConfigOption[] = [],
): SessionConfigOption[] {
  const modes =
    adapter === "codex" ? getAvailableCodexModes() : getAvailableModes();
  const fallbackMode = adapter === "codex" ? "auto" : "plan";
  const currentMode =
    typeof initialMode === "string" &&
    modes.some((mode) => mode.id === initialMode)
      ? initialMode
      : fallbackMode;
  return [
    {
      id: "mode",
      name: "Approval Preset",
      type: "select",
      currentValue: currentMode,
      options: modes.map((mode) => ({
        value: mode.id,
        name: mode.name,
      })),
      category: "mode" as SessionConfigOption["category"],
      description: "Choose an approval and sandboxing preset for your session",
    },
    ...extra,
  ];
}

export function addMissingCloudRuntimeConfigOptions(
  configOptions: SessionConfigOption[],
  adapter: Adapter,
  initialModel?: string,
  initialReasoningEffort?: string,
): SessionConfigOption[] {
  const categories = new Set(configOptions.map((option) => option.category));
  const extras: SessionConfigOption[] = [];

  if (initialModel && !categories.has("model")) {
    extras.push({
      id: "model",
      name: "Model",
      type: "select",
      currentValue: initialModel,
      options: [{ value: initialModel, name: initialModel }],
      category: "model",
    });
  }

  if (initialReasoningEffort && !categories.has("thought_level")) {
    extras.push({
      id: adapter === "codex" ? "reasoning_effort" : "effort",
      name: adapter === "codex" ? "Reasoning" : "Effort",
      type: "select",
      currentValue: initialReasoningEffort,
      options: [
        { value: initialReasoningEffort, name: initialReasoningEffort },
      ],
      category: "thought_level",
    });
  }

  return extras.length > 0 ? [...configOptions, ...extras] : configOptions;
}
