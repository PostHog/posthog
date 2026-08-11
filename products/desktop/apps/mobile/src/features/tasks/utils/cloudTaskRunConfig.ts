import {
  type Adapter,
  type ExecutionMode,
  getReasoningEffortOptions,
  type SupportedReasoningEffort,
  supports1MContext,
  supportsFastMode,
} from "@posthog/shared";
import type { ContextWindow } from "@/features/tasks/composer/options";

export function buildCloudTaskRunConfig({
  adapter,
  mode,
  model,
  reasoning,
  contextWindow,
  fastMode,
}: {
  adapter: Adapter;
  mode: ExecutionMode;
  model: string;
  reasoning: SupportedReasoningEffort;
  contextWindow?: ContextWindow;
  fastMode?: boolean;
}) {
  return {
    adapter,
    model,
    reasoningLevel:
      getReasoningEffortOptions(adapter, model) === null
        ? undefined
        : reasoning,
    initialPermissionMode: mode,
    ...(contextWindow && supports1MContext(model) ? { contextWindow } : {}),
    ...(supportsFastMode(model) ? { fastMode: !!fastMode } : {}),
  };
}
