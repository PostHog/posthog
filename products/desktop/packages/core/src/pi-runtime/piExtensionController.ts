import type {
  PiExtensionEvent,
  RpcExtensionUIResponse,
} from "@posthog/agent/pi/types";
import { inject, injectable } from "inversify";
import {
  createEmptyPiExtensionTaskState,
  createPiExtensionStore,
  type PiExtensionStateAction,
  type PiExtensionStore,
  type PiExtensionTaskState,
  reducePiExtensionState,
} from "./piExtensionStore";
import {
  PI_SESSION_PROVIDER,
  type PiSession,
  type PiSessionProvider,
} from "./piSessionController";

interface PiExtensionSubscription {
  disposed: boolean;
  unsubscribe?: () => void;
}

@injectable()
export class PiExtensionController {
  readonly store: PiExtensionStore = createPiExtensionStore();

  private readonly activeTaskIds = new Set<string>();
  private readonly taskRunIds = new Map<string, string>();
  private readonly sessions = new Map<string, Promise<PiSession>>();
  private readonly connections = new Map<string, Promise<void>>();
  private readonly subscriptions = new Map<string, PiExtensionSubscription>();
  private readonly reconnectAttempts = new Map<string, number>();
  private readonly reconnectTimeouts = new Map<
    string,
    ReturnType<typeof setTimeout>
  >();
  private readonly dialogTimeouts = new Map<
    string,
    Map<string, ReturnType<typeof setTimeout>>
  >();
  private readonly responses = new Map<string, Map<string, Promise<void>>>();
  private readonly versions = new Map<string, number>();

  constructor(
    @inject(PI_SESSION_PROVIDER) private readonly provider: PiSessionProvider,
  ) {}

  connect(taskId: string, taskRunId?: string): Promise<void> {
    const currentTaskRunId = this.taskRunIds.get(taskId);
    if (currentTaskRunId && taskRunId && currentTaskRunId !== taskRunId) {
      this.disconnect(taskId);
    }

    this.activeTaskIds.add(taskId);
    if (taskRunId) {
      this.taskRunIds.set(taskId, taskRunId);
    }
    this.ensureTaskState(taskId);

    if (this.subscriptions.has(taskId)) {
      return Promise.resolve();
    }
    const existing = this.connections.get(taskId);
    if (existing) {
      return existing;
    }

    const connection = this.startSubscription(taskId).finally(() => {
      if (this.connections.get(taskId) === connection) {
        this.connections.delete(taskId);
      }
    });
    this.connections.set(taskId, connection);
    return connection;
  }

  disconnect(taskId: string): void {
    this.activeTaskIds.delete(taskId);
    this.taskRunIds.delete(taskId);
    this.advanceVersion(taskId);
    this.cancelPendingDialogs(taskId);
    this.sessions.delete(taskId);
    this.connections.delete(taskId);
    this.cancelReconnect(taskId);
    this.disposeSubscription(taskId);
    this.responses.delete(taskId);
    this.clearTaskState(taskId);
  }

  respondToExtensionUI(
    taskId: string,
    response: RpcExtensionUIResponse,
  ): Promise<void> {
    if (
      !this.getTaskState(taskId).dialogs.some(({ id }) => id === response.id)
    ) {
      return Promise.resolve();
    }

    const taskResponses = this.responses.get(taskId) ?? new Map();
    const existing = taskResponses.get(response.id);
    if (existing) {
      return existing;
    }

    const version = this.getVersion(taskId);
    const delivery = this.sendResponse(taskId, response)
      .then(() => {
        if (this.getVersion(taskId) === version) {
          this.removeDialog(taskId, response.id);
        }
      })
      .catch((error) => {
        if (
          this.getVersion(taskId) === version &&
          this.getTaskState(taskId).dialogs.some(({ id }) => id === response.id)
        ) {
          this.dispatch(taskId, {
            type: "notification",
            notification: {
              id: `extension-response:${response.id}`,
              message: `Failed to respond to Pi extension: ${String(error)}`,
              notifyType: "error",
            },
          });
        }
        throw error;
      })
      .finally(() => {
        if (taskResponses.get(response.id) === delivery) {
          taskResponses.delete(response.id);
          if (
            taskResponses.size === 0 &&
            this.responses.get(taskId) === taskResponses
          ) {
            this.responses.delete(taskId);
          }
        }
      });

    taskResponses.set(response.id, delivery);
    this.responses.set(taskId, taskResponses);
    return delivery;
  }

  cancelExtensionUI(taskId: string, requestId: string): Promise<void> {
    return this.respondToExtensionUI(taskId, {
      type: "extension_ui_response",
      id: requestId,
      cancelled: true,
    });
  }

  acknowledgeNotification(taskId: string, id: string): void {
    this.dispatch(taskId, { type: "remove-notification", id });
  }

  acknowledgeEditorText(taskId: string, id: string): void {
    this.dispatch(taskId, { type: "consume-editor-text", id });
  }

  private async startSubscription(taskId: string): Promise<void> {
    const subscription: PiExtensionSubscription = { disposed: false };
    this.subscriptions.set(taskId, subscription);

    try {
      const session = await this.getPiSession(taskId);
      if (subscription.disposed) {
        return;
      }
      if (!session.onExtensionEvent) {
        if (this.subscriptions.get(taskId) === subscription) {
          this.subscriptions.delete(taskId);
        }
        return;
      }

      const unsubscribe = session.onExtensionEvent(
        (event) => this.handleEvent(taskId, subscription, event),
        (error) => this.endSubscription(taskId, subscription, error),
        () => this.endSubscription(taskId, subscription),
      );
      if (subscription.disposed) {
        unsubscribe();
      } else {
        subscription.unsubscribe = unsubscribe;
      }
    } catch (error) {
      this.endSubscription(taskId, subscription, error);
    }
  }

  private handleEvent(
    taskId: string,
    subscription: PiExtensionSubscription,
    event: PiExtensionEvent,
  ): void {
    if (this.subscriptions.get(taskId) !== subscription) {
      return;
    }

    this.reconnectAttempts.delete(taskId);
    this.dispatch(taskId, {
      type: "event",
      event,
      id:
        event.type === "extension_error"
          ? globalThis.crypto.randomUUID()
          : event.id,
    });

    if (
      event.type === "extension_ui_request" &&
      (event.method === "select" ||
        event.method === "confirm" ||
        event.method === "input") &&
      event.timeout &&
      event.timeout > 0
    ) {
      this.scheduleDialogTimeout(taskId, event.id, event.timeout);
    }
  }

  private endSubscription(
    taskId: string,
    subscription: PiExtensionSubscription,
    error?: unknown,
  ): void {
    if (this.subscriptions.get(taskId) !== subscription) {
      return;
    }

    this.subscriptions.delete(taskId);
    this.dispose(subscription);
    this.advanceVersion(taskId);
    this.cancelPendingDialogs(taskId);
    this.sessions.delete(taskId);
    this.responses.delete(taskId);
    this.clearTaskState(taskId);

    if (!this.activeTaskIds.has(taskId)) {
      this.cancelReconnect(taskId);
      return;
    }

    if (error !== undefined) {
      this.dispatch(taskId, {
        type: "notification",
        notification: {
          id: `extension-ui-disconnected:${taskId}`,
          message: `Pi extension UI disconnected: ${String(error)}`,
          notifyType: "error",
        },
      });
    }
    this.scheduleReconnect(taskId);
  }

  private scheduleReconnect(taskId: string): void {
    if (!this.activeTaskIds.has(taskId) || this.reconnectTimeouts.has(taskId)) {
      return;
    }

    const attempt = this.reconnectAttempts.get(taskId) ?? 0;
    const delay = Math.min(100 * 2 ** attempt, 1_000);
    this.reconnectAttempts.set(taskId, Math.min(attempt + 1, 4));
    this.reconnectTimeouts.set(
      taskId,
      setTimeout(() => {
        this.reconnectTimeouts.delete(taskId);
        if (this.activeTaskIds.has(taskId)) {
          void this.connect(taskId, this.taskRunIds.get(taskId));
        }
      }, delay),
    );
  }

  private cancelReconnect(taskId: string): void {
    const timeout = this.reconnectTimeouts.get(taskId);
    if (timeout) {
      clearTimeout(timeout);
      this.reconnectTimeouts.delete(taskId);
    }
    this.reconnectAttempts.delete(taskId);
  }

  private disposeSubscription(taskId: string): void {
    const subscription = this.subscriptions.get(taskId);
    if (!subscription) {
      return;
    }
    this.subscriptions.delete(taskId);
    this.dispose(subscription);
  }

  private dispose(subscription: PiExtensionSubscription): void {
    subscription.disposed = true;
    subscription.unsubscribe?.();
  }

  private getPiSession(taskId: string): Promise<PiSession> {
    const existing = this.sessions.get(taskId);
    if (existing) {
      return existing;
    }

    const session = this.provider.get(taskId, this.taskRunIds.get(taskId));
    this.sessions.set(taskId, session);
    void session.catch(() => {
      if (this.sessions.get(taskId) === session) {
        this.sessions.delete(taskId);
      }
    });
    return session;
  }

  private async sendResponse(
    taskId: string,
    response: RpcExtensionUIResponse,
  ): Promise<void> {
    const session = await this.getPiSession(taskId);
    if (!session.respondToExtensionUI) {
      throw new Error("Pi session does not support extension UI responses");
    }
    await session.respondToExtensionUI(response);
  }

  private scheduleDialogTimeout(
    taskId: string,
    requestId: string,
    timeoutMs: number,
  ): void {
    const taskTimeouts = this.dialogTimeouts.get(taskId) ?? new Map();
    if (taskTimeouts.has(requestId)) {
      return;
    }
    taskTimeouts.set(
      requestId,
      setTimeout(() => this.removeDialog(taskId, requestId), timeoutMs),
    );
    this.dialogTimeouts.set(taskId, taskTimeouts);
  }

  private removeDialog(taskId: string, requestId: string): void {
    const taskTimeouts = this.dialogTimeouts.get(taskId);
    const timeout = taskTimeouts?.get(requestId);
    if (timeout) {
      clearTimeout(timeout);
      taskTimeouts?.delete(requestId);
      if (taskTimeouts?.size === 0) {
        this.dialogTimeouts.delete(taskId);
      }
    }
    if (this.store.getState().tasks[taskId]) {
      this.dispatch(taskId, { type: "remove-dialog", id: requestId });
    }
  }

  private cancelPendingDialogs(taskId: string): void {
    const dialogs = this.getTaskState(taskId).dialogs;
    const session = this.sessions.get(taskId);
    if (!session || dialogs.length === 0) {
      return;
    }

    const inFlightResponses = this.responses.get(taskId);
    for (const dialog of dialogs) {
      const cancel = () =>
        session
          .then((resolved) =>
            resolved.respondToExtensionUI?.({
              type: "extension_ui_response",
              id: dialog.id,
              cancelled: true,
            }),
          )
          .catch(() => {});
      const inFlight = inFlightResponses?.get(dialog.id);
      if (inFlight) {
        void inFlight.catch(cancel);
      } else {
        void cancel();
      }
    }
  }

  private getVersion(taskId: string): number {
    return this.versions.get(taskId) ?? 0;
  }

  private advanceVersion(taskId: string): void {
    this.versions.set(taskId, this.getVersion(taskId) + 1);
  }

  private clearTaskState(taskId: string): void {
    const taskTimeouts = this.dialogTimeouts.get(taskId);
    for (const timeout of taskTimeouts?.values() ?? []) {
      clearTimeout(timeout);
    }
    this.dialogTimeouts.delete(taskId);
    this.store.setState((state) => {
      const tasks = { ...state.tasks };
      delete tasks[taskId];
      return { tasks };
    });
  }

  private ensureTaskState(taskId: string): void {
    if (this.store.getState().tasks[taskId]) {
      return;
    }
    this.store.setState((state) => ({
      tasks: {
        ...state.tasks,
        [taskId]: createEmptyPiExtensionTaskState(),
      },
    }));
  }

  private getTaskState(taskId: string): PiExtensionTaskState {
    return (
      this.store.getState().tasks[taskId] ?? createEmptyPiExtensionTaskState()
    );
  }

  private dispatch(taskId: string, action: PiExtensionStateAction): void {
    this.store.setState((state) => ({
      tasks: {
        ...state.tasks,
        [taskId]: reducePiExtensionState(
          state.tasks[taskId] ?? createEmptyPiExtensionTaskState(),
          action,
        ),
      },
    }));
  }
}
