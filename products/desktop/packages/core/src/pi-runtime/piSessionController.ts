import type { PiRemoteRpcClient } from "@posthog/agent/pi/remote-rpc-client";
import type {
  PiExtensionEvent,
  PiNativeModelInfo,
  PiPersistedSessionConfig,
  PiQueueSnapshot,
  PiThinkingLevel,
  RpcExtensionUIResponse,
} from "@posthog/agent/pi/types";
import {
  type AgentConversationEvent,
  classifyPromptFailure,
  type McpToolPermissionDecision,
  type McpToolPermissionRequest,
  type PiMessagingMode,
  type PiRuntimeHealth,
  type PromptFailure,
  type TaskRunStatus,
} from "@posthog/shared";
import { inject, injectable, optional } from "inversify";
import type { AuthService } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";
import { AuthServiceEvent } from "../auth/schemas";
import { parseCommandLine } from "../message-editor/commands";
import {
  AGENT_SESSION_NOTIFIER,
  type AgentSessionNotifier,
} from "../notification/agentSessionNotifications";
import { TASK_SERVICE, type TaskService } from "../task-detail/taskService";
import {
  createEmptyPiControllerSession,
  createPiSessionStore,
  type PiControllerSessionState,
  type PiSessionError,
  type PiSessionStore,
} from "./piSessionStore";

export type {
  PiNativeModelInfo,
  PiQueueSnapshot,
  PiThinkingLevel,
} from "@posthog/agent/pi/types";

export type PiModelSelection = Pick<PiNativeModelInfo, "provider" | "id">;

export interface PiDeferredConfig {
  model?: PiModelSelection;
  thinkingLevel?: PiThinkingLevel;
}

export interface PiSessionNotificationContext {
  taskTitle: string;
  isTaskAuthor?: boolean;
}

export interface PiConversationEventContext {
  isLive: boolean;
}

export const PI_SESSION_PROVIDER = Symbol.for("posthog.pi.sessionProvider");
export const LOCAL_PI_SESSION_FACTORY = Symbol.for(
  "posthog.pi.localSessionFactory",
);

export interface PiSession {
  client: PiRemoteRpcClient;
  readonly resumeRequired?: boolean;
  readonly cloudStatus?: TaskRunStatus;
  readonly taskRunId?: string;
  readonly persistedConfig?: PiPersistedSessionConfig | null;
  retry?(): Promise<void>;
  getQueue(): Promise<PiQueueSnapshot>;
  clearQueue(): Promise<PiQueueSnapshot>;
  sendUserMessage?(
    type: "prompt" | "steer" | "follow_up",
    message: string,
    artifactIds: string[],
    id: string,
  ): Promise<void>;
  health(): Promise<PiRuntimeHealth>;
  getConversation(): Promise<AgentConversationEvent[]>;
  onConversationEvent(
    onEvent: (
      event: AgentConversationEvent,
      context?: PiConversationEventContext,
    ) => void,
    onError: (error: unknown) => void,
    onCloudStatus?: (status: TaskRunStatus) => void,
  ): () => void;
  onMcpToolPermissionRequest?(
    onRequest: (request: McpToolPermissionRequest) => void,
    onError: (error: unknown) => void,
  ): () => void;
  respondMcpToolPermission?(
    request: McpToolPermissionRequest,
    decision: McpToolPermissionDecision,
  ): Promise<void>;
  onExtensionEvent?(
    onEvent: (event: PiExtensionEvent) => void,
    onError: (error: unknown) => void,
    onComplete?: () => void,
  ): () => void;
  respondToExtensionUI?(response: RpcExtensionUIResponse): Promise<void>;
}

export interface PiSessionFactory {
  get(taskId: string, taskRunId?: string): Promise<PiSession>;
  readSessionConfig?(
    downloadUrl: string,
  ): Promise<PiPersistedSessionConfig | null>;
}

export type PiSessionProvider = PiSessionFactory;

export type PiSubmitResult = "prompt" | "steer" | "followUp" | "compact";

type PiTurnState =
  | { phase: "active"; startedAt?: number; stopReason?: string }
  | { phase: "completed" };

type PiOperation =
  | "prompt"
  | "compact"
  | "model"
  | "thinking"
  | "bash"
  | "cancel"
  | "queue"
  | "retry"
  | "restart";

export class PiOperationError extends Error {
  constructor(readonly failure: PiSessionError) {
    super(failure.message);
    this.name = "PiOperationError";
  }
}

function normalizeSessionError(error: unknown): {
  title: string;
  message: string;
  retryable: boolean;
} {
  const value = error as {
    title?: unknown;
    message?: unknown;
    retryable?: unknown;
  };
  return {
    title: typeof value?.title === "string" ? value.title : "Connection failed",
    message: typeof value?.message === "string" ? value.message : String(error),
    retryable: value?.retryable !== false,
  };
}

@injectable()
export class PiSessionController {
  readonly store: PiSessionStore = createPiSessionStore();

  private readonly sessions = new Map<string, Promise<PiSession>>();
  private readonly subscriptions = new Map<string, () => void>();
  private readonly liveEvents = new Map<string, AgentConversationEvent[]>();
  private readonly connections = new Map<string, Promise<void>>();
  private readonly readiness = new Map<string, Promise<void>>();
  private readonly sessionVersions = new Map<string, number>();
  private readonly queueRevisions = new Map<string, number>();
  private readonly queuesToRestore = new Map<string, PiQueueSnapshot>();
  private readonly cancelAuthRestoration = new Map<string, () => void>();
  private readonly taskRunIds = new Map<string, string>();
  private readonly activeTaskIds = new Set<string>();
  private readonly notificationContexts = new Map<
    string,
    PiSessionNotificationContext
  >();
  private readonly turnStates = new Map<string, PiTurnState>();

  constructor(
    @inject(PI_SESSION_PROVIDER) private readonly provider: PiSessionProvider,
    @inject(TASK_SERVICE) private readonly taskService: TaskService,
    @inject(AUTH_SERVICE)
    @optional()
    private readonly authService?: AuthService,
    @inject(AGENT_SESSION_NOTIFIER)
    @optional()
    private readonly notifier?: AgentSessionNotifier,
  ) {
    this.authService?.on(AuthServiceEvent.StateChanged, (state) => {
      if (state.status === "anonymous") {
        this.disconnectAll();
      }
    });
  }

  setNotificationContext(
    taskId: string,
    context: PiSessionNotificationContext,
  ): void {
    this.notificationContexts.set(taskId, context);
  }

  ensureConnected(taskId: string, taskRunId?: string): Promise<void> {
    this.activeTaskIds.add(taskId);
    this.bindTaskRun(taskId, taskRunId);
    this.ensureSubscription(taskId);

    const existing = this.readiness.get(taskId);
    if (existing) {
      return existing;
    }

    this.updateSession(taskId, {
      connectionState: "connecting",
      error: undefined,
    });
    const connectedSessionVersion = this.getSessionVersion(taskId);
    const readiness = this.ensureConnectedInternal(taskId)
      .then(() => {
        if (this.getSessionVersion(taskId) === connectedSessionVersion) {
          this.updateSession(taskId, {
            connectionState: "connected",
            error: undefined,
          });
        }
      })
      .catch((error) => {
        if (this.getSessionVersion(taskId) === connectedSessionVersion) {
          this.applySessionError(taskId, error);
        }
        throw error;
      })
      .finally(() => {
        if (this.readiness.get(taskId) === readiness) {
          this.readiness.delete(taskId);
        }
        this.disposeInactiveSessionIfIdle(taskId);
      });
    this.readiness.set(taskId, readiness);
    return readiness;
  }

  connect(taskId: string, taskRunId?: string): Promise<void> {
    this.activeTaskIds.add(taskId);
    this.bindTaskRun(taskId, taskRunId);
    this.ensureSubscription(taskId);
    return this.connectSession(taskId);
  }

  private connectSession(taskId: string): Promise<void> {
    const existing = this.connections.get(taskId);
    if (existing) {
      return existing;
    }

    this.updateSession(taskId, { error: undefined });

    const connection = this.loadSession(taskId).finally(() => {
      if (this.connections.get(taskId) === connection) {
        this.connections.delete(taskId);
      }
    });
    this.connections.set(taskId, connection);
    return connection;
  }

  release(taskId: string): void {
    this.activeTaskIds.delete(taskId);
    this.disposeInactiveSessionIfIdle(taskId);
  }

  disconnect(taskId: string): void {
    this.activeTaskIds.delete(taskId);
    this.disposeTask(taskId);
  }

  disconnectAll(): void {
    const taskIds = new Set([
      ...this.activeTaskIds,
      ...this.sessions.keys(),
      ...this.subscriptions.keys(),
      ...this.notificationContexts.keys(),
    ]);
    for (const taskId of taskIds) {
      this.disconnect(taskId);
    }
  }

  async retry(taskId: string): Promise<void> {
    if (this.getSession(taskId).connectionState === "connecting") {
      return;
    }
    this.updateSession(taskId, {
      connectionState: "connecting",
      error: undefined,
    });
    const taskRunId = this.taskRunIds.get(taskId);
    this.captureQueueForRestore(taskId);
    try {
      const session = await this.getPiSession(taskId);
      await session.retry?.();
      this.resetTransport(taskId);
      await this.ensureConnected(taskId, taskRunId);
    } catch (error) {
      throw this.recordOperationFailure(taskId, "retry", error);
    }
  }

  async respondMcpToolPermission(
    taskId: string,
    request: McpToolPermissionRequest,
    decision: McpToolPermissionDecision,
  ): Promise<void> {
    const session = await this.getPiSession(taskId);
    if (!session.respondMcpToolPermission) {
      throw new Error("MCP tool permissions are unavailable for this session");
    }
    await session.respondMcpToolPermission(request, decision);
    const requests = new Map(this.getSession(taskId).mcpToolPermissionRequests);
    requests.delete(request.requestId);
    this.updateSession(taskId, { mcpToolPermissionRequests: requests });
  }

  async clearQueue(taskId: string): Promise<PiQueueSnapshot> {
    try {
      const session = await this.getPiSession(taskId);
      const queue = await session.clearQueue();
      this.queuesToRestore.delete(taskId);
      this.applyQueue(taskId, { steering: [], followUp: [] });
      return queue;
    } catch (error) {
      throw this.recordOperationFailure(taskId, "queue", error);
    }
  }

  async restart(taskId: string): Promise<void> {
    if (this.getSession(taskId).connectionState === "connecting") {
      return;
    }
    const taskRunId = this.taskRunIds.get(taskId);
    if (!taskRunId) {
      await this.retry(taskId);
      return;
    }

    this.updateSession(taskId, {
      connectionState: "connecting",
      error: undefined,
    });
    this.captureQueueForRestore(taskId);
    try {
      const resumedRun = await this.taskService.resumeCloudPiRun(
        taskId,
        taskRunId,
      );
      this.resetTransport(taskId);
      await this.ensureConnected(taskId, resumedRun.id);
    } catch (error) {
      throw this.recordOperationFailure(taskId, "restart", error);
    }
  }

  retryUnhealthyCloudSessions(): void {
    for (const [taskId, session] of Object.entries(
      this.store.getState().sessions,
    )) {
      if (
        this.activeTaskIds.has(taskId) &&
        session.cloudStatus !== undefined &&
        session.error?.retryable &&
        (session.connectionState === "disconnected" ||
          session.connectionState === "error")
      ) {
        void this.retry(taskId).catch(() => {});
      }
    }
  }

  getSubmitAction(
    text: string,
    isStreaming: boolean,
    messagingMode: PiMessagingMode,
  ): PiSubmitResult {
    const command = parseCommandLine(text.trim());
    if (command?.name === "compact") {
      return "compact";
    }

    if (!isStreaming) {
      return "prompt";
    }

    return messagingMode === "steer" ? "steer" : "followUp";
  }

  async submit(
    taskId: string,
    text: string,
    isStreaming: boolean,
    messagingMode: PiMessagingMode,
    deferredConfig?: PiDeferredConfig,
  ): Promise<PiSubmitResult> {
    const message = text.trim();
    const action = this.getSubmitAction(message, isStreaming, messagingMode);

    const currentSession = await this.getPiSession(taskId);
    const submissionSessionVersion = this.getSessionVersion(taskId);
    if (this.getSession(taskId).authRestoring) {
      throw this.recordOperationFailure(
        taskId,
        "prompt",
        new Error("Authentication required while the session restores"),
        undefined,
        message,
      );
    }
    if (currentSession.sendUserMessage) {
      try {
        await this.waitForAuthRestoration(taskId);
        if (this.getSessionVersion(taskId) !== submissionSessionVersion) {
          throw new Error(
            "Authentication required; submission cancelled after session changed",
          );
        }
      } catch (error) {
        throw this.recordOperationFailure(
          taskId,
          "prompt",
          error,
          undefined,
          message,
        );
      }
    }
    const controllerSession = this.getSession(taskId);
    if (controllerSession.error?.scope === "operation") {
      this.updateSession(taskId, { error: undefined });
    }
    const wasStreaming = controllerSession.status?.isStreaming ?? false;
    const queuesMessage = action === "steer" || action === "followUp";
    const queuedMessageCount =
      controllerSession.queue.steering.length +
      controllerSession.queue.followUp.length;
    if (queuesMessage && queuedMessageCount > 0) {
      throw new Error("Pi already has a queued message");
    }
    const refreshAfterSubmit =
      action === "compact" ||
      this.isExtensionCommand(controllerSession, message);
    if (action === "compact") {
      try {
        const session = await this.getWritablePiSession(taskId);
        const command = parseCommandLine(message);
        const customInstructions = command?.args?.trim() || undefined;
        await session.client.compact(customInstructions);
      } catch (error) {
        throw this.recordOperationFailure(taskId, "compact", error);
      }
    } else {
      const commandType = action === "followUp" ? "follow_up" : action;
      const messageId = currentSession.sendUserMessage
        ? globalThis.crypto.randomUUID()
        : undefined;
      const hasOptimisticTranscriptMessage = Boolean(
        messageId && action === "prompt",
      );
      if (messageId && hasOptimisticTranscriptMessage) {
        this.appendOptimisticUserMessage(taskId, messageId, message);
      }
      if (queuesMessage) {
        this.applyQueue(taskId, {
          steering: action === "steer" ? [message] : [],
          followUp: action === "followUp" ? [message] : [],
        });
      }
      this.markTurnPending(taskId);
      if (currentSession.resumeRequired) {
        this.updateSession(taskId, { connectionState: "connecting" });
      }

      try {
        const session = await this.getWritablePiSession(taskId);
        await this.applyDeferredConfig(session, deferredConfig);
        this.markTurnPending(taskId);
        if (session.sendUserMessage && messageId) {
          const taskRunId = this.taskRunIds.get(taskId);
          const prepared = taskRunId
            ? await this.taskService.prepareCloudPiMessage(
                taskId,
                taskRunId,
                message,
              )
            : { content: message, artifactIds: [] };
          await this.sendCloudUserMessage(
            taskId,
            session,
            commandType,
            prepared.content,
            prepared.artifactIds,
            messageId,
          );
        } else if (action === "prompt") {
          await session.client.prompt(message);
        } else if (action === "steer") {
          await session.client.steer(message);
        } else {
          await session.client.followUp(message);
        }
        if (queuesMessage) {
          await this.refreshQueue(taskId, session);
        }
      } catch (error) {
        if (messageId && hasOptimisticTranscriptMessage) {
          this.removeUserMessage(taskId, messageId);
        }
        if (queuesMessage) {
          this.applyQueue(taskId, controllerSession.queue);
        }
        this.setTurnStreaming(taskId, wasStreaming);
        const operation = queuesMessage ? "queue" : "prompt";
        throw this.recordOperationFailure(taskId, operation, error);
      }
    }

    if (refreshAfterSubmit) {
      await this.refreshStatus(taskId);
    }
    return action;
  }

  async setModel(taskId: string, model: PiModelSelection): Promise<void> {
    try {
      const session = await this.getPiSession(taskId);
      await session.client.setModel(model.provider, model.id);
      await this.refreshStatus(taskId);
      await this.refreshStats(taskId);
      const thinkingLevels = await session.client.getAvailableThinkingLevels();
      this.updateSession(taskId, {
        thinkingLevels,
        thinkingLevelsLoaded: true,
      });
    } catch (error) {
      throw this.recordOperationFailure(taskId, "model", error);
    }
  }

  async setThinkingLevel(
    taskId: string,
    level: PiThinkingLevel,
  ): Promise<void> {
    try {
      const session = await this.getPiSession(taskId);
      await session.client.setThinkingLevel(level);
      await this.refreshStatus(taskId);
    } catch (error) {
      throw this.recordOperationFailure(taskId, "thinking", error);
    }
  }

  async bash(taskId: string, command: string): Promise<void> {
    this.updateSession(taskId, { isBashRunning: true });
    try {
      const session = await this.getPiSession(taskId);
      await session.client.bash(command);
    } catch (error) {
      throw this.recordOperationFailure(taskId, "bash", error);
    } finally {
      this.updateSession(taskId, { isBashRunning: false });
    }
  }

  async abort(taskId: string): Promise<void> {
    const turn = this.turnStates.get(taskId);
    if (turn?.phase === "active") {
      this.turnStates.set(taskId, { ...turn, stopReason: "cancelled" });
    }
    try {
      const session = await this.getPiSession(taskId);
      await session.client.abort();
      await this.refreshStatus(taskId);
    } catch (error) {
      throw this.recordOperationFailure(taskId, "cancel", error);
    }
  }

  async abortBash(taskId: string): Promise<void> {
    try {
      const session = await this.getPiSession(taskId);
      await session.client.abortBash();
      this.updateSession(taskId, { isBashRunning: false });
    } catch (error) {
      throw this.recordOperationFailure(taskId, "cancel", error);
    }
  }

  private async ensureConnectedInternal(taskId: string): Promise<void> {
    const session = await this.getPiSession(taskId);
    const health = await session.health();
    if (health.state === "cold") {
      const taskRunId = this.taskRunIds.get(taskId);
      const result = taskRunId
        ? await this.taskService.openTask(taskId, taskRunId)
        : await this.taskService.openTask(taskId);
      if (!result.success) {
        throw new Error(result.error);
      }

      this.disposeConversationSubscription(taskId);
      this.sessions.delete(taskId);
      this.connections.delete(taskId);
      this.ensureSubscription(taskId);
    }

    await this.connectSession(taskId);
  }

  private ensureSubscription(taskId: string): void {
    if (this.subscriptions.has(taskId)) {
      return;
    }

    let disposed = false;
    let unsubscribeConversation: (() => void) | undefined;
    let unsubscribePermission: (() => void) | undefined;
    void this.getPiSession(taskId)
      .then((session) => {
        if (disposed) {
          return;
        }
        this.applyPersistedConfig(taskId, session);
        this.updateSession(taskId, { cloudStatus: session.cloudStatus });
        unsubscribeConversation = session.onConversationEvent(
          (event, context) => this.handleEvent(taskId, event, context),
          (error) => this.applySessionError(taskId, error),
          (cloudStatus) => this.handleCloudStatus(taskId, cloudStatus),
        );
        unsubscribePermission = session.onMcpToolPermissionRequest?.(
          (request) => {
            const requests = new Map(
              this.getSession(taskId).mcpToolPermissionRequests,
            );
            if (requests.has(request.requestId)) {
              return;
            }
            requests.set(request.requestId, request);
            this.updateSession(taskId, {
              mcpToolPermissionRequests: requests,
            });
            const context = this.notificationContexts.get(taskId);
            if (context) {
              this.notifier?.notify({
                kind: "needs_input",
                taskId,
                taskTitle: context.taskTitle,
                isTaskAuthor: context.isTaskAuthor,
              });
            }
          },
          (error) => this.applySessionError(taskId, error),
        );
      })
      .catch((error) => this.applySessionError(taskId, error));
    this.subscriptions.set(taskId, () => {
      disposed = true;
      unsubscribeConversation?.();
      unsubscribePermission?.();
    });
  }

  private applyPersistedConfig(taskId: string, session: PiSession): void {
    const config = session.persistedConfig;
    if (!config) {
      return;
    }

    const current = this.getSession(taskId);
    const status = current.status
      ? {
          ...current.status,
          model: config.model ?? undefined,
          thinkingLevel: config.thinkingLevel,
        }
      : {
          isStreaming: false,
          isCompacting: false,
          thinkingLevel: config.thinkingLevel,
          model: config.model ?? undefined,
          steeringMode: "all" as const,
          followUpMode: "all" as const,
          sessionId: session.taskRunId ?? taskId,
          autoCompactionEnabled: true,
          messageCount: current.events.length,
          pendingMessageCount: 0,
        };
    this.updateSession(taskId, {
      status,
      models: config.model ? [config.model] : [],
      modelsLoaded: true,
      thinkingLevels: [config.thinkingLevel],
      thinkingLevelsLoaded: true,
    });
  }

  private async loadSession(taskId: string): Promise<void> {
    const connectedSessionVersion = this.getSessionVersion(taskId);
    try {
      const session = await this.getPiSession(taskId);
      const queueRevision = this.queueRevisions.get(taskId) ?? 0;
      const retainedStats = this.getSession(taskId).stats;
      const [events, status, queue, stats] = await Promise.all([
        session.getConversation(),
        session.client.getState(),
        session.getQueue(),
        session.client.getSessionStats().catch(() => retainedStats),
      ]);
      if (this.getSessionVersion(taskId) !== connectedSessionVersion) {
        return;
      }

      const currentSession = this.getSession(taskId);
      const conversationEvents = events.filter(
        (event) => event.type !== "queue_update",
      );
      const liveEvents = this.liveEvents.get(taskId) ?? [];
      const newLiveEvents = this.reconcileLiveEvents(
        conversationEvents,
        liveEvents,
      );
      this.liveEvents.set(taskId, newLiveEvents);
      const historyUserMessageIds = new Set(
        conversationEvents.flatMap((event) =>
          event.type === "user_message" ? [event.id] : [],
        ),
      );
      const optimisticEvents = currentSession.events.filter(
        (event) =>
          event.sourceId?.startsWith("optimistic:") &&
          (event.type !== "user_message" ||
            !historyUserMessageIds.has(event.id)),
      );
      const reconciledEvents = [
        ...conversationEvents,
        ...newLiveEvents,
        ...optimisticEvents,
      ];
      const resolvedQueue =
        (this.queueRevisions.get(taskId) ?? 0) === queueRevision
          ? queue
          : currentSession.queue;
      const resolvedStatus = {
        ...status,
        model: status.model
          ? { provider: status.model.provider, id: status.model.id }
          : (session.persistedConfig?.model ?? undefined),
        pendingMessageCount:
          resolvedQueue.steering.length + resolvedQueue.followUp.length,
      };

      this.reconcileTurnState(
        taskId,
        reconciledEvents,
        resolvedStatus.isStreaming,
      );

      this.setSession(taskId, {
        connectionState: "connected",
        events: reconciledEvents,
        status: resolvedStatus,
        stats,
        models: currentSession.models,
        modelsLoaded: currentSession.modelsLoaded,
        thinkingLevels: currentSession.thinkingLevels,
        thinkingLevelsLoaded: currentSession.thinkingLevelsLoaded,
        commands: currentSession.commands,
        queue: resolvedQueue,
        error:
          currentSession.error?.scope === "operation"
            ? currentSession.error
            : undefined,
        authRestoring: currentSession.authRestoring,
        isBashRunning: false,
        mcpToolPermissionRequests: currentSession.mcpToolPermissionRequests,
      });

      await this.restoreQueueIfNeeded(taskId, session, resolvedStatus);

      await Promise.all([
        session.client.getAvailableModels().then((models) => {
          if (this.getSessionVersion(taskId) === connectedSessionVersion) {
            const persistedModel = session.persistedConfig?.model;
            this.updateSession(taskId, {
              models:
                models.length > 0
                  ? models
                  : persistedModel
                    ? [persistedModel]
                    : [],
              modelsLoaded: true,
            });
          }
        }),
        session.client.getAvailableThinkingLevels().then((thinkingLevels) => {
          if (this.getSessionVersion(taskId) === connectedSessionVersion) {
            const persistedThinkingLevel =
              session.persistedConfig?.thinkingLevel;
            this.updateSession(taskId, {
              thinkingLevels:
                thinkingLevels.length > 0
                  ? thinkingLevels
                  : persistedThinkingLevel
                    ? [persistedThinkingLevel]
                    : [],
              thinkingLevelsLoaded: true,
            });
          }
        }),
        session.client.getCommands().then((commands) => {
          if (this.getSessionVersion(taskId) === connectedSessionVersion) {
            this.updateSession(taskId, { commands });
          }
        }),
      ]);

      this.disposeInactiveSessionIfIdle(taskId);
    } catch (error) {
      if (this.getSessionVersion(taskId) === connectedSessionVersion) {
        this.applySessionError(taskId, error);
      }
      throw error;
    }
  }

  private handleEvent(
    taskId: string,
    event: AgentConversationEvent,
    context?: PiConversationEventContext,
  ): void {
    if (event.type === "queue_update") {
      const queue = {
        steering: event.steering,
        followUp: event.followUp,
      };
      this.applyQueue(taskId, queue);
      return;
    }

    const session = this.getSession(taskId);
    if (
      event.sourceId &&
      session.events.some((existing) => existing.sourceId === event.sourceId)
    ) {
      return;
    }

    const isLive = context?.isLive ?? true;
    this.applyTurnEvent(taskId, event, isLive);

    if (event.type === "runtime_error") {
      this.recordOperationFailure(
        taskId,
        "prompt",
        new Error(event.message),
        event.errorType,
      );
    }

    const liveEvents = [...(this.liveEvents.get(taskId) ?? []), event];
    this.liveEvents.set(taskId, liveEvents);
    let status = session.status;
    if (status && event.type === "runtime_status") {
      if (event.status === "compacting") {
        status = { ...status, isCompacting: !event.isComplete };
      } else if (event.status === "compacting_failed") {
        status = { ...status, isCompacting: false };
        this.recordOperationFailure(
          taskId,
          "compact",
          new Error(event.error ?? event.message ?? "Compaction failed"),
        );
      }
    }
    const isDirectBashEvent =
      (event.type === "tool_call_started" ||
        event.type === "tool_call_updated") &&
      event.toolCall.origin === "user_shell";
    const hasTurnActivity =
      !isDirectBashEvent &&
      (event.type === "assistant_message_chunk" ||
        event.type === "assistant_thought_chunk" ||
        event.type === "tool_call_started" ||
        event.type === "tool_call_updated");
    if (status && hasTurnActivity) {
      status = { ...status, isStreaming: true };
    }
    if (status && event.type === "turn_completed") {
      status = { ...status, isStreaming: false };
    }

    const existingUserMessageIndex =
      event.type === "user_message"
        ? session.events.findIndex(
            (candidate) =>
              candidate.type === "user_message" && candidate.id === event.id,
          )
        : -1;
    const events = [...session.events];
    if (existingUserMessageIndex >= 0) {
      events[existingUserMessageIndex] = event;
    } else {
      events.push(event);
    }

    const latestSession = this.getSession(taskId);
    const preserveConnectionError =
      event.type === "runtime_error" &&
      latestSession.error?.scope === "connection";
    const preserveOperationError = latestSession.error?.scope === "operation";
    this.updateSession(taskId, {
      connectionState:
        event.type === "progress" || preserveConnectionError
          ? latestSession.connectionState
          : "connected",
      events,
      status,
      error:
        preserveConnectionError || preserveOperationError
          ? latestSession.error
          : undefined,
    });

    if (event.type === "turn_completed") {
      void this.refreshStats(taskId);
      this.disposeInactiveSessionIfIdle(taskId);
    }
  }

  private reconcileTurnState(
    taskId: string,
    events: AgentConversationEvent[],
    isStreaming: boolean,
  ): void {
    this.turnStates.delete(taskId);
    for (const event of events) {
      this.applyTurnEvent(taskId, event, false);
    }
    if (isStreaming && this.turnStates.get(taskId)?.phase !== "active") {
      this.turnStates.set(taskId, { phase: "active" });
    }
  }

  private applyTurnEvent(
    taskId: string,
    event: AgentConversationEvent,
    isLive: boolean,
  ): void {
    const current = this.turnStates.get(taskId);
    const activeTurn = current?.phase === "active" ? current : undefined;
    const isDirectBash =
      (event.type === "tool_call_started" ||
        event.type === "tool_call_updated") &&
      event.toolCall.origin === "user_shell";
    const hasTurnActivity =
      event.type === "user_message" ||
      event.type === "assistant_message_chunk" ||
      event.type === "assistant_thought_chunk" ||
      (!isDirectBash &&
        (event.type === "tool_call_started" ||
          event.type === "tool_call_updated"));

    if (hasTurnActivity) {
      this.turnStates.set(taskId, {
        phase: "active",
        startedAt:
          activeTurn?.startedAt ??
          (event.type === "user_message" ? event.timestamp : undefined),
      });
      return;
    }

    if (event.type === "runtime_error") {
      this.turnStates.set(taskId, {
        phase: "active",
        startedAt: activeTurn?.startedAt,
        stopReason: "failed",
      });
      return;
    }

    if (event.type !== "turn_completed") {
      return;
    }

    this.turnStates.set(taskId, { phase: "completed" });
    if (!isLive || current?.phase === "completed") {
      return;
    }

    const notificationContext = this.notificationContexts.get(taskId);
    if (!notificationContext) {
      return;
    }

    const stopReason = this.normalizeStopReason(
      event.stopReason ?? activeTurn?.stopReason,
    );
    const durationMs = activeTurn?.startedAt
      ? Math.max(0, event.timestamp - activeTurn.startedAt)
      : undefined;
    this.notifier?.notify({
      kind: "turn_completed",
      taskId,
      taskTitle: notificationContext.taskTitle,
      stopReason,
      durationMs,
      isTaskAuthor: notificationContext.isTaskAuthor,
    });
  }

  private normalizeStopReason(stopReason: string | undefined): string {
    if (stopReason === "stop" || stopReason === undefined) {
      return "end_turn";
    }
    if (stopReason === "aborted") {
      return "cancelled";
    }
    if (stopReason === "error") {
      return "failed";
    }
    return stopReason;
  }

  private handleCloudStatus(taskId: string, cloudStatus: TaskRunStatus): void {
    this.updateSession(taskId, { cloudStatus });
  }

  private async refreshStats(taskId: string): Promise<void> {
    const sessionVersion = this.getSessionVersion(taskId);
    try {
      const session = await this.getPiSession(taskId);
      const stats = await session.client.getSessionStats();
      if (this.getSessionVersion(taskId) === sessionVersion) {
        this.updateSession(taskId, { stats });
      }
    } catch {
      return;
    }
  }

  private reconcileLiveEvents(
    historyEvents: AgentConversationEvent[],
    liveEvents: AgentConversationEvent[],
  ): AgentConversationEvent[] {
    const historySourceIds = new Set(
      historyEvents.flatMap((event) =>
        event.sourceId ? [event.sourceId] : [],
      ),
    );
    return liveEvents.filter(
      (event) => !event.sourceId || !historySourceIds.has(event.sourceId),
    );
  }

  acknowledgeOperationFailure(taskId: string, failureId: string): void {
    const session = this.getSession(taskId);
    if (
      session.error?.scope === "operation" &&
      session.error.id === failureId
    ) {
      this.updateSession(taskId, { error: undefined });
    }
  }

  private async waitForAuthRestoration(taskId: string): Promise<void> {
    if (
      !this.authService ||
      this.authService.getState().status !== "restoring"
    ) {
      return;
    }

    this.updateSession(taskId, { authRestoring: true });
    try {
      await new Promise<void>((resolve, reject) => {
        const cleanup = () => {
          this.authService?.off(
            AuthServiceEvent.StateChanged,
            handleStateChange,
          );
          this.cancelAuthRestoration.delete(taskId);
        };
        const handleStateChange = (
          state: ReturnType<AuthService["getState"]>,
        ) => {
          if (state.status === "restoring") {
            return;
          }
          cleanup();
          if (state.status === "authenticated") {
            resolve();
          } else {
            reject(new Error("Authentication required for cloud commands"));
          }
        };
        this.cancelAuthRestoration.set(taskId, () => {
          cleanup();
          reject(
            new Error(
              "Authentication required; submission cancelled while restoring",
            ),
          );
        });
        this.authService?.on(AuthServiceEvent.StateChanged, handleStateChange);
        if (this.authService) {
          handleStateChange(this.authService.getState());
        }
      });
    } finally {
      this.cancelAuthRestoration.delete(taskId);
      this.updateSession(taskId, { authRestoring: false });
    }
  }

  private recordOperationFailure(
    taskId: string,
    operation: PiOperation,
    error: unknown,
    errorType?: string,
    recoveryPrompt?: string,
  ): PiOperationError {
    const details = (error as { data?: { details?: string } })?.data?.details;
    const classified = classifyPromptFailure(error, details, errorType);
    const retryable =
      classified.retryable ||
      ((operation === "retry" || operation === "restart") &&
        classified.kind === "unknown");
    const scope =
      classified.kind === "fatal_session" ||
      operation === "retry" ||
      operation === "restart"
        ? "connection"
        : "operation";
    const failure: PiSessionError = {
      id: globalThis.crypto.randomUUID(),
      scope,
      kind: classified.kind,
      title: this.errorTitleForOperation(operation, classified),
      message: classified.message,
      retryable,
      limitCause: classified.limitCause,
      recoveryPrompt,
    };
    this.updateSession(taskId, {
      error: failure,
      ...(scope === "connection"
        ? {
            connectionState: retryable ? "disconnected" : "error",
          }
        : {}),
    });
    return new PiOperationError(failure);
  }

  private errorTitleForOperation(
    operation: PiOperation,
    failure: PromptFailure,
  ): string {
    if (failure.kind === "usage_limit") {
      return "Usage limit reached";
    }
    if (failure.kind === "transient") {
      return "Provider temporarily unavailable";
    }
    if (failure.kind === "authentication") {
      return "Authentication required";
    }
    const titles: Record<PiOperation, string> = {
      prompt: "Failed to send message",
      compact: "Failed to compact Pi context",
      model: "Failed to change Pi model",
      thinking: "Failed to change Pi thinking level",
      bash: "Failed to run Pi bash command",
      cancel: "Failed to stop Pi",
      queue: "Failed to update queued message",
      retry: "Failed to reconnect to Pi",
      restart: "Failed to restart Pi",
    };
    return titles[operation];
  }

  private captureQueueForRestore(taskId: string): void {
    const queue = this.getSession(taskId).queue;
    if (queue.steering.length === 0 && queue.followUp.length === 0) {
      return;
    }
    this.queuesToRestore.set(taskId, {
      steering: [...queue.steering],
      followUp: [...queue.followUp],
    });
  }

  private async restoreQueueIfNeeded(
    taskId: string,
    session: PiSession,
    status: NonNullable<PiControllerSessionState["status"]>,
  ): Promise<void> {
    const queue = this.getSession(taskId).queue;
    const queueToRestore = this.queuesToRestore.get(taskId);
    if (!queueToRestore) {
      return;
    }
    if (queue.steering.length > 0 || queue.followUp.length > 0) {
      this.queuesToRestore.delete(taskId);
      return;
    }

    const messages = [
      ...queueToRestore.steering.map((content) => ({
        content,
        mode: "steer" as const,
      })),
      ...queueToRestore.followUp.map((content) => ({
        content,
        mode: "follow_up" as const,
      })),
    ];
    this.queuesToRestore.delete(taskId);
    if (!status.isStreaming) {
      const first = messages.shift();
      if (first) {
        await session.client.prompt(first.content);
      }
    }

    for (const message of messages) {
      if (message.mode === "steer") {
        await session.client.steer(message.content);
      } else {
        await session.client.followUp(message.content);
      }
    }
  }

  private async refreshQueue(
    taskId: string,
    session: PiSession,
  ): Promise<void> {
    try {
      const queue = await session.getQueue();
      this.applyQueue(taskId, queue);
    } catch {
      return;
    }
  }

  private applyQueue(taskId: string, queue: PiQueueSnapshot): void {
    this.queueRevisions.set(taskId, (this.queueRevisions.get(taskId) ?? 0) + 1);
    this.updateSession(taskId, {
      queue,
      status: this.withPendingMessageCount(taskId, queue),
    });
  }

  private withPendingMessageCount(
    taskId: string,
    queue: PiQueueSnapshot,
  ): PiControllerSessionState["status"] {
    const status = this.getSession(taskId).status;
    if (!status) {
      return undefined;
    }
    return {
      ...status,
      pendingMessageCount: queue.steering.length + queue.followUp.length,
    };
  }

  private isExtensionCommand(
    session: PiControllerSessionState,
    message: string,
  ): boolean {
    const command = parseCommandLine(message);
    if (!command) {
      return false;
    }
    return session.commands.some(
      (available) =>
        available.name === command.name && available.source === "extension",
    );
  }

  private markTurnPending(taskId: string): void {
    const current = this.turnStates.get(taskId);
    const startedAt =
      current?.phase === "active" ? current.startedAt : Date.now();
    this.turnStates.set(taskId, { phase: "active", startedAt });
    this.setTurnStreaming(taskId, true);
  }

  private setTurnStreaming(taskId: string, isStreaming: boolean): void {
    const session = this.getSession(taskId);
    if (!session.status) {
      return;
    }

    this.updateSession(taskId, {
      status: { ...session.status, isStreaming },
    });
  }

  private appendOptimisticUserMessage(
    taskId: string,
    messageId: string,
    content: string,
  ): void {
    const session = this.getSession(taskId);
    this.updateSession(taskId, {
      events: [
        ...session.events,
        {
          type: "user_message",
          id: messageId,
          sourceId: `optimistic:${messageId}`,
          timestamp: Date.now(),
          content: [{ type: "text", text: content }],
        },
      ],
    });
  }

  private removeUserMessage(taskId: string, messageId: string): void {
    const session = this.getSession(taskId);
    this.updateSession(taskId, {
      events: session.events.filter(
        (event) => event.type !== "user_message" || event.id !== messageId,
      ),
    });
  }

  private async applyDeferredConfig(
    session: PiSession,
    config: PiDeferredConfig | undefined,
  ): Promise<void> {
    if (!config) {
      return;
    }

    if (config.model) {
      await session.client.setModel(config.model.provider, config.model.id);
    }
    if (config.thinkingLevel) {
      await session.client.setThinkingLevel(config.thinkingLevel);
    }
  }

  private async refreshStatus(taskId: string): Promise<void> {
    const session = await this.getPiSession(taskId);
    const status = await session.client.getState();
    this.updateSession(taskId, { status });
  }

  private async sendCloudUserMessage(
    taskId: string,
    session: PiSession,
    type: "prompt" | "steer" | "follow_up",
    content: string,
    artifactIds: string[],
    messageId: string,
  ): Promise<void> {
    if (!session.sendUserMessage) {
      throw new Error("Cloud Pi session cannot send messages");
    }

    try {
      await session.sendUserMessage(type, content, artifactIds, messageId);
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const taskRunId = this.taskRunIds.get(taskId) ?? session.taskRunId;
      if (!taskRunId || !message.includes("No active sandbox")) {
        throw error;
      }

      const resumedRun = await this.taskService.resumeCloudPiRun(
        taskId,
        taskRunId,
      );
      this.resetTransport(taskId);
      await this.ensureConnected(taskId, resumedRun.id);
      const resumedSession = await this.getPiSession(taskId);
      if (!resumedSession.sendUserMessage) {
        throw new Error("Resumed cloud Pi session cannot send messages");
      }
      await resumedSession.sendUserMessage(
        type,
        content,
        artifactIds,
        messageId,
      );
    }
  }

  private async getWritablePiSession(taskId: string): Promise<PiSession> {
    const session = await this.getPiSession(taskId);
    const taskRunId = this.taskRunIds.get(taskId) ?? session.taskRunId;
    if (!session.resumeRequired || !taskRunId) {
      return session;
    }

    const resumedRun = await this.taskService.resumeCloudPiRun(
      taskId,
      taskRunId,
    );
    this.resetTransport(taskId);
    this.taskRunIds.delete(taskId);
    this.liveEvents.delete(taskId);
    this.queueRevisions.delete(taskId);
    this.queuesToRestore.delete(taskId);
    this.activeTaskIds.delete(taskId);
    await this.ensureConnected(taskId, resumedRun.id);
    return this.getPiSession(taskId);
  }

  private bindTaskRun(taskId: string, taskRunId?: string): void {
    const currentTaskRunId = this.taskRunIds.get(taskId);
    if (!taskRunId || currentTaskRunId === taskRunId) {
      return;
    }

    if (currentTaskRunId || this.sessions.has(taskId)) {
      this.resetTransport(taskId);
      this.liveEvents.delete(taskId);
    }
    this.taskRunIds.set(taskId, taskRunId);
  }

  private disposeInactiveSessionIfIdle(taskId: string): void {
    if (
      this.activeTaskIds.has(taskId) ||
      this.shouldRetainInactiveSession(taskId)
    ) {
      return;
    }
    this.disposeTask(taskId);
  }

  private shouldRetainInactiveSession(taskId: string): boolean {
    const session = this.getSession(taskId);
    if (
      session.connectionState === "connecting" ||
      session.status?.isStreaming ||
      this.turnStates.get(taskId)?.phase === "active"
    ) {
      return true;
    }
    return (
      session.cloudStatus !== undefined &&
      session.cloudStatus !== "completed" &&
      session.cloudStatus !== "failed" &&
      session.cloudStatus !== "cancelled"
    );
  }

  private disposeTask(taskId: string): void {
    this.cancelAuthRestoration.get(taskId)?.();
    this.resetTransport(taskId);
    this.taskRunIds.delete(taskId);
    this.liveEvents.delete(taskId);
    this.queueRevisions.delete(taskId);
    this.queuesToRestore.delete(taskId);
    this.turnStates.delete(taskId);
    this.notificationContexts.delete(taskId);
    this.updateSession(taskId, { mcpToolPermissionRequests: new Map() });
  }

  private resetTransport(taskId: string): void {
    this.advanceSessionVersion(taskId);
    this.disposeConversationSubscription(taskId);
    this.sessions.delete(taskId);
    this.connections.delete(taskId);
    this.readiness.delete(taskId);
  }

  private disposeConversationSubscription(taskId: string): void {
    this.subscriptions.get(taskId)?.();
    this.subscriptions.delete(taskId);
  }

  private getPiSession(taskId: string): Promise<PiSession> {
    const existing = this.sessions.get(taskId);
    if (existing) {
      return existing;
    }

    const session = this.provider
      .get(taskId, this.taskRunIds.get(taskId))
      .then((resolved) => {
        if (resolved.taskRunId && !this.taskRunIds.has(taskId)) {
          this.taskRunIds.set(taskId, resolved.taskRunId);
        }
        return resolved;
      });
    this.sessions.set(taskId, session);
    void session.catch(() => {
      if (this.sessions.get(taskId) === session) {
        this.sessions.delete(taskId);
      }
    });
    return session;
  }

  private getSessionVersion(taskId: string): number {
    return this.sessionVersions.get(taskId) ?? 0;
  }

  private advanceSessionVersion(taskId: string): void {
    this.sessionVersions.set(taskId, this.getSessionVersion(taskId) + 1);
  }

  private getSession(taskId: string): PiControllerSessionState {
    return (
      this.store.getState().sessions[taskId] ?? createEmptyPiControllerSession()
    );
  }

  private setSession(taskId: string, session: PiControllerSessionState): void {
    this.store.setState((state) => ({
      sessions: { ...state.sessions, [taskId]: session },
    }));
  }

  private applySessionError(taskId: string, error: unknown): void {
    const failure = normalizeSessionError(error);
    const classified = classifyPromptFailure(error);
    this.updateSession(taskId, {
      connectionState: failure.retryable ? "disconnected" : "error",
      error: {
        id: globalThis.crypto.randomUUID(),
        scope: "connection",
        kind: classified.kind,
        title: failure.title,
        message: failure.message,
        retryable: failure.retryable,
        limitCause: classified.limitCause,
      },
    });
  }

  private updateSession(
    taskId: string,
    update: Partial<PiControllerSessionState>,
  ): void {
    this.setSession(taskId, { ...this.getSession(taskId), ...update });
  }
}
