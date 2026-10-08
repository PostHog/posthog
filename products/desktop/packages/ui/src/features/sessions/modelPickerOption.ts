import {
  type ModelPickerOption,
  type ModelPickerOptionBase,
  toModelPickerOption,
} from "@posthog/core/billing/modelPricing";
import { logger } from "@posthog/ui/shell/logger";

const log = logger.scope("model-picker");

const reported = new Set<string>();

/**
 * The picker's model conversion, with a report when the price table has no row
 * for a model. One report per id, because the pickers convert on every render.
 */
export function toPickerOption(
  model: ModelPickerOptionBase,
): ModelPickerOption {
  const option = toModelPickerOption(model);
  if (option.kind === "unpriced" && !reported.has(option.value)) {
    reported.add(option.value);
    log.warn("no price for model", { model: option.value });
  }
  return option;
}
