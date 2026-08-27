import type {
  ExtensionFactory,
  InlineExtension,
  SessionEntry,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { buildTaskSystemPrompt, type TaskContext } from "./task-system-prompt";

export const POSTHOG_PI_TASK_CONTEXT_ENTRY_TYPE = "posthog.pi.task-context";

type NamedInlineExtension = Exclude<InlineExtension, ExtensionFactory>;

function isTaskContext(value: unknown): value is TaskContext {
  if (!value || typeof value !== "object") {
    return false;
  }

  const context = value as Partial<TaskContext>;
  const hasValidDirectories =
    context.additionalDirectories === undefined ||
    (Array.isArray(context.additionalDirectories) &&
      context.additionalDirectories.every(
        (directory) => typeof directory === "string",
      ));

  return (
    typeof context.projectId === "number" &&
    typeof context.apiHost === "string" &&
    typeof context.taskId === "string" &&
    typeof context.cwd === "string" &&
    (context.environment === "local" || context.environment === "cloud") &&
    (context.customInstructions === undefined ||
      typeof context.customInstructions === "string") &&
    hasValidDirectories &&
    (context.channelMode === undefined ||
      typeof context.channelMode === "boolean") &&
    (context.additionalInstructions === undefined ||
      typeof context.additionalInstructions === "string")
  );
}

export function readPersistedPiTaskContext(
  entries: SessionEntry[],
): TaskContext | null {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (
      entry?.type !== "custom" ||
      entry.customType !== POSTHOG_PI_TASK_CONTEXT_ENTRY_TYPE
    ) {
      continue;
    }
    const data = entry.data as { context?: unknown } | undefined;
    if (isTaskContext(data?.context)) {
      return data.context;
    }
  }

  return null;
}

export function resolvePiTaskContext(
  sessionManager: SessionManager,
  context: TaskContext | undefined,
): TaskContext | null {
  const persistedContext = readPersistedPiTaskContext(
    sessionManager.getEntries(),
  );
  if (!context) {
    return persistedContext;
  }

  const resolvedContext = {
    ...persistedContext,
    ...context,
    customInstructions:
      context.customInstructions ?? persistedContext?.customInstructions,
    additionalDirectories:
      context.additionalDirectories ?? persistedContext?.additionalDirectories,
    channelMode: context.channelMode ?? persistedContext?.channelMode,
    additionalInstructions:
      context.additionalInstructions ??
      persistedContext?.additionalInstructions,
  };
  if (JSON.stringify(resolvedContext) !== JSON.stringify(persistedContext)) {
    sessionManager.appendCustomEntry(POSTHOG_PI_TASK_CONTEXT_ENTRY_TYPE, {
      context: resolvedContext,
    });
  }
  return resolvedContext;
}

export function createPiTaskSystemPromptExtension(
  context: TaskContext | null,
): NamedInlineExtension {
  return {
    name: "posthog-task-system-prompt",
    factory: (pi) => {
      if (!context) {
        return;
      }
      pi.on("before_agent_start", (event) => ({
        systemPrompt: `${event.systemPrompt}\n\n${buildTaskSystemPrompt(context)}`,
      }));
    },
  };
}
