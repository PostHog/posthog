import { CloudCommandError } from "@posthog/api-client/posthog-client";
import type {
  CloudTaskUpdatePayload,
  Task,
  TaskRunStatus,
} from "@posthog/shared";
import * as Haptics from "expo-haptics";
import { create } from "zustand";
import { getClient } from "@/lib/client";
import { currentRunConfig } from "@/lib/composer";
import { type WatchHandle, watchRun } from "@/lib/engine";
import { logger } from "@/lib/logger";
import {
  type Block,
  closeOpenAgent,
  foldEntries,
  type PermissionRequest,
} from "@/lib/transcript";

const log = logger.scope("session");

const TERMINAL: ReadonlySet<string> = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export interface TaskSession {
  taskId: string;
  runId: string;
  blocks: Block[];
  runStatus: TaskRunStatus | null;
  stage: string | null;
  connected: boolean;
  turnActive: boolean;
  awaitingInput: boolean;
  error: string | null;
  permissions: Record<string, PermissionRequest>;
  // Prompts sent from this device, so their echo in the log is not shown twice.
  localEchoes: Set<string>;
  // Last prompt sent, kept so a dead sandbox can be resumed with it.
  lastPrompt: string | null;
  // A replacement run is being created for a finished one.
  resuming: boolean;
}

interface SessionState {
  sessions: Record<string, TaskSession>;
  // A chat that exists on screen before its task does. `adopt` moves it under
  // the real task id once the run is created; `fail` leaves the prompt with an error.
  startPending: (tempId: string, prompt: string, localId: string) => void;
  adopt: (tempId: string, task: Task) => void;
  failPending: (tempId: string, message: string) => void;
  connect: (task: Task) => void;
  disconnect: (taskId: string) => void;
  reconnect: () => void;
  sendPrompt: (
    taskId: string,
    text: string,
    localId?: string,
  ) => Promise<string | null>;
  cancelTurn: (taskId: string) => Promise<void>;
  stopRun: (taskId: string) => Promise<void>;
  respondToPermission: (
    taskId: string,
    toolCallId: string,
    optionId: string,
  ) => Promise<void>;
}

const handles = new Map<string, WatchHandle>();

// A finished run answers commands with 409 "workflow has ended"; a dead
// sandbox with 404. Both mean: start a replacement run carrying the message.
function runIsGone(error: CloudCommandError): boolean {
  return (
    error.isSandboxInactive() ||
    error.status === 409 ||
    !!error.backendError?.toLowerCase().includes("workflow has ended")
  );
}

function emptySession(taskId: string, runId: string): TaskSession {
  return {
    taskId,
    runId,
    blocks: [],
    runStatus: null,
    stage: null,
    connected: false,
    turnActive: false,
    awaitingInput: false,
    error: null,
    permissions: {},
    localEchoes: new Set(),
    lastPrompt: null,
    resuming: false,
  };
}

export const useSessions = create<SessionState>((set, get) => {
  const patch = (
    taskId: string,
    fn: (s: TaskSession) => Partial<TaskSession>,
  ): void => {
    set((state) => {
      const current = state.sessions[taskId];
      if (!current) return state;
      return {
        sessions: {
          ...state.sessions,
          [taskId]: { ...current, ...fn(current) },
        },
      };
    });
  };

  const applyUpdate = (
    taskId: string,
    update: CloudTaskUpdatePayload,
  ): void => {
    const session = get().sessions[taskId];
    if (!session || session.runId !== update.runId) return;

    if (update.kind === "error") {
      patch(taskId, () => ({ error: update.errorMessage, connected: false }));
      return;
    }

    if (update.kind === "permission_request") {
      const toolCallId = update.toolCall?.toolCallId;
      if (!toolCallId) return;
      patch(taskId, (s) => ({
        permissions: {
          ...s.permissions,
          [toolCallId]: {
            requestId: update.requestId,
            toolCallId,
            title: update.toolCall.title,
            input: update.toolCall.rawInput,
            options: update.options,
          },
        },
      }));
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(
        () => {},
      );
      return;
    }

    if (update.kind === "status") {
      patch(taskId, (s) => {
        const terminal = !!update.status && TERMINAL.has(update.status);
        return {
          runStatus: update.status ?? s.runStatus,
          stage: update.stage ?? s.stage,
          turnActive: terminal ? false : s.turnActive,
          error: update.errorMessage ?? s.error,
        };
      });
      return;
    }

    const isSnapshot = update.kind === "snapshot";
    const echoes = isSnapshot ? new Set<string>() : session.localEchoes;
    const folded = foldEntries(
      isSnapshot ? [] : session.blocks,
      update.newEntries,
      echoes,
    );

    patch(taskId, (s) => {
      const permissions = isSnapshot ? {} : { ...s.permissions };
      for (const request of folded.permissionRequests) {
        permissions[request.toolCallId] = request;
      }
      for (const requestId of folded.resolvedRequestIds) {
        for (const [key, value] of Object.entries(permissions)) {
          if (value.requestId === requestId) delete permissions[key];
        }
      }
      // A tool call that already finished no longer needs an answer.
      for (const block of folded.blocks) {
        if (
          block.kind === "tool" &&
          block.status !== "pending" &&
          permissions[block.id]
        ) {
          delete permissions[block.id];
        }
      }

      let turnActive = s.turnActive;
      if (folded.externalUserMessages > 0) turnActive = true;
      if (folded.turnEnded) turnActive = false;
      const status = isSnapshot ? (update.status ?? s.runStatus) : s.runStatus;
      if (status && TERMINAL.has(status)) turnActive = false;
      // A reopened live run with an unfinished agent block is still working.
      if (isSnapshot && status && !TERMINAL.has(status)) {
        const tail = folded.blocks[folded.blocks.length - 1];
        turnActive =
          tail?.kind === "user" ||
          (tail?.kind === "agent" && !tail.complete) ||
          tail?.kind === "tool";
      }

      return {
        blocks: folded.blocks,
        connected: true,
        turnActive,
        awaitingInput: folded.awaitingInput,
        error:
          folded.errorMessage ??
          (isSnapshot ? (update.errorMessage ?? null) : s.error),
        permissions,
        localEchoes: echoes,
        runStatus: status ?? s.runStatus,
        stage: isSnapshot ? (update.stage ?? s.stage) : s.stage,
      };
    });

    if (!isSnapshot && folded.turnEnded && session.turnActive) {
      Haptics.notificationAsync(
        folded.turnFailed
          ? Haptics.NotificationFeedbackType.Error
          : Haptics.NotificationFeedbackType.Success,
      ).catch(() => {});
    }
  };

  const watch = (taskId: string, runId: string): void => {
    handles.get(taskId)?.stop();
    handles.set(
      taskId,
      watchRun(taskId, runId, (update) => applyUpdate(taskId, update)),
    );
  };

  const resumeRun = async (taskId: string, prompt: string): Promise<void> => {
    const session = get().sessions[taskId];
    if (!session) return;
    log.info("Sandbox gone, resuming run", {
      taskId,
      previousRunId: session.runId,
    });
    const task = await getClient().runTaskInCloud(taskId, undefined, {
      resumeFromRunId: session.runId,
      pendingUserMessage: prompt,
      ...currentRunConfig(),
    });
    const runId = task.latest_run?.id;
    if (!runId) throw new Error("Resume did not return a run");
    set((state) => ({
      sessions: {
        ...state.sessions,
        [taskId]: {
          ...emptySession(taskId, runId),
          blocks: state.sessions[taskId]?.blocks ?? [],
          turnActive: true,
          lastPrompt: prompt,
          resuming: true,
        },
      },
    }));
    watch(taskId, runId);
  };

  return {
    sessions: {},

    startPending: (tempId, prompt, localId) => {
      set((state) => ({
        sessions: {
          ...state.sessions,
          [tempId]: {
            ...emptySession(tempId, ""),
            blocks: [{ kind: "user", id: localId, text: prompt }],
            runStatus: "queued",
            turnActive: true,
            localEchoes: new Set([prompt]),
            lastPrompt: prompt,
          },
        },
      }));
    },

    adopt: (tempId, task) => {
      const runId = task.latest_run?.id;
      const pending = get().sessions[tempId];
      if (!runId || !pending) return;
      set((state) => {
        const sessions = { ...state.sessions };
        delete sessions[tempId];
        sessions[task.id] = {
          ...pending,
          taskId: task.id,
          runId,
          runStatus: task.latest_run?.status ?? "queued",
        };
        return { sessions };
      });
      watch(task.id, runId);
    },

    failPending: (tempId, message) => {
      patch(tempId, () => ({ turnActive: false, error: message }));
    },

    connect: (task) => {
      const runId = task.latest_run?.id;
      if (!runId) return;
      const existing = get().sessions[task.id];
      if (existing?.runId === runId && handles.has(task.id)) return;
      set((state) => ({
        sessions: {
          ...state.sessions,
          [task.id]: emptySession(task.id, runId),
        },
      }));
      watch(task.id, runId);
    },

    disconnect: (taskId) => {
      handles.get(taskId)?.stop();
      handles.delete(taskId);
    },

    reconnect: () => {
      for (const handle of handles.values()) handle.reconnectIfDisconnected();
    },

    sendPrompt: async (taskId, text, localId = `local-${Date.now()}`) => {
      const session = get().sessions[taskId];
      if (!session) return null;
      const echoes = new Set(session.localEchoes);
      echoes.add(text);
      patch(taskId, (s) => {
        const blocks = [...s.blocks];
        closeOpenAgent(blocks);
        blocks.push({ kind: "user", id: localId, text });
        return {
          blocks,
          turnActive: true,
          awaitingInput: false,
          error: null,
          localEchoes: echoes,
          lastPrompt: text,
        };
      });
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
      try {
        await getClient().sendCloudRunCommand(
          taskId,
          session.runId,
          "user_message",
          { content: text },
        );
      } catch (error) {
        if (error instanceof CloudCommandError && runIsGone(error)) {
          patch(taskId, () => ({ resuming: true }));
          try {
            await resumeRun(taskId, text);
          } catch (resumeError) {
            patch(taskId, () => ({
              resuming: false,
              turnActive: false,
              error:
                resumeError instanceof Error
                  ? resumeError.message
                  : String(resumeError),
            }));
          }
          return localId;
        }
        echoes.delete(text);
        patch(taskId, () => ({
          turnActive: false,
          error: error instanceof Error ? error.message : String(error),
        }));
      }
      return localId;
    },

    cancelTurn: async (taskId) => {
      const session = get().sessions[taskId];
      if (!session) return;
      try {
        await getClient().sendCloudRunCommand(taskId, session.runId, "cancel");
        patch(taskId, () => ({ turnActive: false }));
      } catch (error) {
        patch(taskId, () => ({
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    },

    stopRun: async (taskId) => {
      const session = get().sessions[taskId];
      if (!session) return;
      await getClient().cancelTaskRun(taskId, session.runId);
      patch(taskId, () => ({ turnActive: false, runStatus: "cancelled" }));
    },

    respondToPermission: async (taskId, toolCallId, optionId) => {
      const session = get().sessions[taskId];
      const request = session?.permissions[toolCallId];
      if (!session || !request) return;
      patch(taskId, (s) => ({
        permissions: {
          ...s.permissions,
          [toolCallId]: { ...request, chosenOptionId: optionId },
        },
        turnActive: true,
      }));
      try {
        await getClient().sendCloudRunCommand(
          taskId,
          session.runId,
          "permission_response",
          {
            requestId: request.requestId,
            toolCallId,
            optionId,
          },
        );
        patch(taskId, (s) => {
          const permissions = { ...s.permissions };
          delete permissions[toolCallId];
          return { permissions };
        });
      } catch (error) {
        patch(taskId, (s) => ({
          permissions: { ...s.permissions, [toolCallId]: request },
          error: error instanceof Error ? error.message : String(error),
        }));
      }
    },
  };
});
