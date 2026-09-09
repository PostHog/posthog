import type {
  ExtensionAPI,
  ExtensionContext,
  ExtensionFactory,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import { Container } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const CURRENT_WORK_STATUS_KEY = "current-work";
const CURRENT_WORK_TOOL_NAME = "set_current_work";
const MIN_STATUS_LENGTH = 3;
const MAX_STATUS_LENGTH = 72;

function normalizeStatus(value: string): string {
  return value.trim().replace(/\.+$/, "");
}

function isCurrentWorkToolCall(event: ToolCallEvent): boolean {
  return event.toolName === CURRENT_WORK_TOOL_NAME;
}

function currentWorkFromEvent(event: ToolCallEvent): string | null {
  if (!isCurrentWorkToolCall(event)) {
    return null;
  }

  const input = event.input as Record<string, unknown>;
  if (typeof input.status !== "string") {
    return null;
  }

  const status = normalizeStatus(input.status);
  if (
    status.length < MIN_STATUS_LENGTH ||
    status.length > MAX_STATUS_LENGTH ||
    /[\r\n]/.test(status)
  ) {
    return null;
  }

  return status;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) {
    return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  }
  return `${seconds}s`;
}

export function createCurrentWorkExtension(): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    let currentWork: string | undefined;
    let startedAt: number | undefined;
    let interval: ReturnType<typeof setInterval> | undefined;

    const updateWorkingMessage = (
      context: Pick<ExtensionContext, "ui">,
    ): void => {
      const elapsed = startedAt === undefined ? 0 : Date.now() - startedAt;
      context.ui.setWorkingMessage(
        `${currentWork ?? "Working"}... (${formatElapsed(elapsed)})`,
      );
    };

    const stopTimer = (context: Pick<ExtensionContext, "ui">): void => {
      if (interval) {
        clearInterval(interval);
        interval = undefined;
      }
      startedAt = undefined;
      context.ui.setWorkingMessage();
    };

    const startTimer = (context: Pick<ExtensionContext, "ui">): void => {
      if (interval) {
        clearInterval(interval);
      }
      startedAt = Date.now();
      updateWorkingMessage(context);
      interval = setInterval(() => updateWorkingMessage(context), 1000);
    };

    const setCurrentWork = (
      context: Pick<ExtensionContext, "mode" | "ui">,
      status: string,
    ): void => {
      currentWork = status;
      if (context.mode === "rpc") {
        context.ui.setStatus(CURRENT_WORK_STATUS_KEY, status);
      }
      updateWorkingMessage(context);
    };

    const clearCurrentWork = (
      context: Pick<ExtensionContext, "mode" | "ui">,
    ): void => {
      currentWork = undefined;
      if (context.mode === "rpc") {
        context.ui.setStatus(CURRENT_WORK_STATUS_KEY, undefined);
      }
    };

    pi.registerTool({
      name: CURRENT_WORK_TOOL_NAME,
      label: "Set current work",
      description:
        "Set the visible current-work status before starting a meaningful tool-use phase.",
      promptSnippet:
        "Set the visible current-work status before starting a meaningful tool-use phase",
      promptGuidelines: [
        "Use set_current_work before a meaningful new task phase when practical. Use a concise present-participle phrase that names the current phase, such as 'Inspecting the test setup' or 'Writing regression tests'. Keep the phrase at the task-phase level, not per individual tool call.",
      ],
      renderShell: "self",
      renderCall: () => new Container(),
      renderResult: () => new Container(),
      parameters: Type.Object({
        status: Type.String({
          description:
            "A concise present-participle phrase for the current task phase, without ending punctuation.",
          minLength: MIN_STATUS_LENGTH,
          maxLength: MAX_STATUS_LENGTH,
        }),
      }),
      execute: async (_toolCallId, params, _signal, _onUpdate, context) => {
        const status = normalizeStatus(params.status);
        if (
          status.length < MIN_STATUS_LENGTH ||
          status.length > MAX_STATUS_LENGTH ||
          /[\r\n]/.test(status)
        ) {
          throw new Error(
            `Status must be a single-line phrase of ${MIN_STATUS_LENGTH}-${MAX_STATUS_LENGTH} characters.`,
          );
        }

        setCurrentWork(context, status);

        return {
          content: [{ type: "text", text: `Current work: ${status}` }],
          details: { status },
        };
      },
    });

    pi.on("tool_call", (event, context) => {
      const status = currentWorkFromEvent(event);
      if (status) {
        setCurrentWork(context, status);
      }
    });

    pi.on("agent_start", (_event, context) => {
      startTimer(context);
    });

    pi.on("agent_end", (_event, context) => {
      stopTimer(context);
    });

    pi.on("agent_settled", (_event, context) => {
      clearCurrentWork(context);
    });

    pi.on("session_shutdown", (_event, context) => {
      stopTimer(context);
      clearCurrentWork(context);
    });
  };
}

export default function currentWork(pi: ExtensionAPI): void {
  createCurrentWorkExtension()(pi);
}
