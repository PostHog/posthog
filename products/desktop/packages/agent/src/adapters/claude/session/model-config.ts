import type { SessionConfigSelectOption } from "@agentclientprotocol/sdk";
import { compareModelsForPicker } from "../../../gateway-models";

export interface ModelConfigOptions {
  currentModelId: string;
  options: SessionConfigSelectOption[];
}

/**
 * Restrict gateway model options to the user's `availableModels` allowlist
 * from settings.json. Unknown allowlist entries are dropped; if every entry
 * is unknown we fall back to the gateway list as a safety net.
 */
export function applyAvailableModelsAllowlist(
  modelOptions: ModelConfigOptions,
  allowlist: string[],
): ModelConfigOptions {
  const filtered: SessionConfigSelectOption[] = [];
  const seen = new Set<string>();

  for (const entry of allowlist) {
    const trimmed = entry.trim();
    if (!trimmed || seen.has(trimmed)) continue;

    const match = modelOptions.options.find((o) => o.value === trimmed);
    if (match) {
      filtered.push(match);
      seen.add(trimmed);
    }
  }

  if (filtered.length === 0) return modelOptions;

  // The allowlist is a filter, not a display order: keep the picker's ordering.
  filtered.sort((a, b) => compareModelsForPicker(a.value, b.value));

  const currentModelId = filtered.some(
    (o) => o.value === modelOptions.currentModelId,
  )
    ? modelOptions.currentModelId
    : filtered[0].value;

  return { currentModelId, options: filtered };
}

export function resolveInitialModelId(
  modelOptions: ModelConfigOptions,
  preferredModelIds: Array<string | undefined>,
): string {
  const allowedModelIds = new Set(modelOptions.options.map((opt) => opt.value));

  for (const candidate of preferredModelIds) {
    const trimmed = candidate?.trim();
    if (trimmed && allowedModelIds.has(trimmed)) {
      return trimmed;
    }
  }

  return modelOptions.currentModelId;
}
