import type {
  PiCommand,
  PiModelOption,
  PiQueueMode,
  PiSessionStatus,
  PiThinkingLevel,
} from "@posthog/agent/pi/types";
import type {
  AgentConversationEvent,
  PiMessagingMode,
  PiRuntimeHealth,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { parseCommandLine } from "../message-editor/commands";
import { TASK_SERVICE, type TaskService } from "../task-detail/taskService";
import {
  createEmptyPiControllerSession,
  createPiSessionStore,
  type PiControllerSessionState,
  type PiSessionStore,
} from "./piSessionStore";

export type {
  PiModelOption,
  PiQueueMode,
  PiThinkingLevel,
} from "@posthog/agent/pi/types";

export const PI_SESSION_CLIENT = Symbol.for("posthog.pi.sessionClient");

export interface PiSessionClient {
  health(taskId: string): Promise<PiRuntimeHealth>;
  conversation(taskId: string): Promise<AgentConversationEvent[]>;
  status(taskId: string): Promise<PiSessionStatus>;
  availableModels(taskId: string): Promise<PiModelOption[]>;
  commands(taskId: string): Promise<PiCommand[]>;
  subscribe(
    taskId: string,
    onEvent: (event: AgentConversationEvent) => void,
    onError: (error: unknown) => void,
  ): () => void;
  prompt(taskId: string, prompt: string): Promise<void>;
  steer(taskId: string, message: string): Promise<void>;
  followUp(taskId: string, message: string): Promise<void>;
  compact(taskId: string, customInstructions?: string): Promise<unknown>;
  setModel(
    taskId: string,
    provider: string,
    modelId: string,
  ): Promise<{ provider: string; id: string }>;
  setThinkingLevel(taskId: string, level: PiThinkingLevel): Promise<void>;
  setSteeringMode(taskId: string, mode: PiQueueMode): Promise<void>;
  setFollowUpMode(taskId: string, mode: PiQueueMode): Promise<void>;
  bash(taskId: string, command: string): Promise<unknown>;
  abort(taskId: string): Promise<void>;
  abortBash(taskId: string): Promise<void>;
}

export type PiSubmitResult = "prompt" | "steer" | "followUp" | "compact";

@injectable()
export class PiSessionController {
  readonly store: PiSessionStore = createPiSessionStore();

  private readonly subscriptions = new Map<string, () => void>();
  private readonly liveEvents = new Map<string, AgentConversationEvent[]>();
  private readonly connections = new Map<string, Promise<void>>();
  private readonly readiness = new Map<string, Promise<void>>();

  constructor(
    @inject(PI_SESSION_CLIENT) private readonly client: PiSessionClient,
    @inject(TASK_SERVICE) private readonly taskService: TaskService,
  ) {}

  ensureConnected(taskId: string): Promise<void> {
    this.ensureSubscription(taskId);

    const existing = this.readiness.get(taskId);
    if (existing) {
      return existing;
    }

    this.updateSession(taskId, {
      connectionState: "connecting",
      error: undefined,
    });
    const readiness = this.ensureConnectedInternal(taskId)
      .then(() => {
        this.updateSession(taskId, { connectionState: "connected" });
      })
      .catch((error) => {
        this.updateSession(taskId, {
          connectionState: "failed",
          error: error instanceof Error ? error.message : String(error),
        });
        throw error;
      })
      .finally(() => {
        this.readiness.delete(taskId);
      });
    this.readiness.set(taskId, readiness);
    return readiness;
  }

  connect(taskId: string): Promise<void> {
    this.ensureSubscription(taskId);

    const existing = this.connections.get(taskId);
    if (existing) {
      return existing;
    }

    this.updateSession(taskId, { error: undefined });

    const connection = this.loadSession(taskId).finally(() => {
      this.connections.delete(taskId);
    });
    this.connections.set(taskId, connection);
    return connection;
  }

  disconnect(taskId: string): void {
    this.subscriptions.get(taskId)?.();
    this.subscriptions.delete(taskId);
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
  ): Promise<PiSubmitResult> {
    const message = text.trim();
    const action = this.getSubmitAction(message, isStreaming, messagingMode);

    try {
      if (action === "compact") {
        const command = parseCommandLine(message);
        const customInstructions = command?.args?.trim() || undefined;
        await this.client.compact(taskId, customInstructions);
        await this.refreshConversation(taskId);
      } else if (action === "prompt") {
        await this.client.prompt(taskId, message);
      } else if (action === "steer") {
        await this.client.steer(taskId, message);
      } else {
        await this.client.followUp(taskId, message);
      }

      await this.refreshStatus(taskId);
      return action;
    } catch (error) {
      this.updateSession(taskId, {
        error: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }

  async setModel(taskId: string, model: PiModelOption): Promise<void> {
    await this.client.setModel(taskId, model.provider, model.id);
    await this.refreshStatus(taskId);
  }

  async setThinkingLevel(
    taskId: string,
    level: PiThinkingLevel,
  ): Promise<void> {
    await this.client.setThinkingLevel(taskId, level);
    await this.refreshStatus(taskId);
  }

  async setQueueMode(
    taskId: string,
    messagingMode: PiMessagingMode,
    queueMode: PiQueueMode,
  ): Promise<void> {
    if (messagingMode === "steer") {
      await this.client.setSteeringMode(taskId, queueMode);
    } else {
      await this.client.setFollowUpMode(taskId, queueMode);
    }
    await this.refreshStatus(taskId);
  }

  async bash(taskId: string, command: string): Promise<void> {
    this.updateSession(taskId, { isBashRunning: true });
    try {
      await this.client.bash(taskId, command);
      await this.refreshConversation(taskId);
    } finally {
      this.updateSession(taskId, { isBashRunning: false });
    }
  }

  async abort(taskId: string): Promise<void> {
    await this.client.abort(taskId);
    await this.refreshStatus(taskId);
  }

  async abortBash(taskId: string): Promise<void> {
    await this.client.abortBash(taskId);
    this.updateSession(taskId, { isBashRunning: false });
  }

  private async ensureConnectedInternal(taskId: string): Promise<void> {
    const health = await this.client.health(taskId);
    if (health.state === "cold") {
      const result = await this.taskService.openTask(taskId);
      if (!result.success) {
        throw new Error(result.error);
      }
    }

    await this.connect(taskId);
  }

  private ensureSubscription(taskId: string): void {
    if (this.subscriptions.has(taskId)) {
      return;
    }

    const unsubscribe = this.client.subscribe(
      taskId,
      (event) => this.handleEvent(taskId, event),
      (error) => {
        this.updateSession(taskId, {
          error: error instanceof Error ? error.message : String(error),
        });
      },
    );
    this.subscriptions.set(taskId, unsubscribe);
  }

  private async loadSession(taskId: string): Promise<void> {
    try {
      const [events, status] = await Promise.all([
        this.client.conversation(taskId),
        this.client.status(taskId),
      ]);
      const liveEvents = status.isStreaming
        ? (this.liveEvents.get(taskId) ?? [])
        : [];
      const currentSession = this.getSession(taskId);
      this.liveEvents.set(taskId, liveEvents);
      this.setSession(taskId, {
        connectionState: "connected",
        events: [...events, ...liveEvents],
        status,
        models: currentSession.models,
        commands: currentSession.commands,
        isBashRunning: false,
        error: undefined,
      });

      const [models, commands] = await Promise.all([
        this.client.availableModels(taskId),
        this.client.commands(taskId),
      ]);
      this.updateSession(taskId, { models, commands });
    } catch (error) {
      this.updateSession(taskId, {
        error: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }
  }

  private handleEvent(taskId: string, event: AgentConversationEvent): void {
    const liveEvents = [...(this.liveEvents.get(taskId) ?? []), event];
    this.liveEvents.set(taskId, liveEvents);
    const session = this.getSession(taskId);
    let status = session.status;
    if (status && event.type === "runtime_status") {
      if (event.status === "compacting") {
        status = { ...status, isCompacting: !event.isComplete };
      } else if (event.status === "compacting_failed") {
        status = { ...status, isCompacting: false };
      }
    }
    if (status && event.type === "turn_completed") {
      status = { ...status, isStreaming: false };
    }

    this.updateSession(taskId, {
      events: [...session.events, event],
      status,
    });

    if (event.type === "turn_completed") {
      const capturedCount = liveEvents.length;
      void this.refreshConversation(taskId, capturedCount);
    }
  }

  private async refreshConversation(
    taskId: string,
    capturedLiveCount?: number,
  ): Promise<void> {
    const events = await this.client.conversation(taskId);
    const liveEvents = this.liveEvents.get(taskId) ?? [];
    const remainingEvents =
      capturedLiveCount === undefined
        ? []
        : liveEvents.slice(capturedLiveCount);
    this.liveEvents.set(taskId, remainingEvents);
    this.updateSession(taskId, {
      events: [...events, ...remainingEvents],
    });
  }

  private async refreshStatus(taskId: string): Promise<void> {
    const status = await this.client.status(taskId);
    this.updateSession(taskId, { status });
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

  private updateSession(
    taskId: string,
    update: Partial<PiControllerSessionState>,
  ): void {
    this.setSession(taskId, { ...this.getSession(taskId), ...update });
  }
}
