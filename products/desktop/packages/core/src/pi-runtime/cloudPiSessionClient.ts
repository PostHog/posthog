import {
  type PiRemoteRpcClient,
  RemotePiRpcClient,
} from "@posthog/agent/pi/remote-rpc-client";
import type {
  PiMcpPermissionResponseCommand,
  RpcCommand,
} from "@posthog/agent/pi/rpc-transport";
import type {
  PiPersistedSessionConfig,
  PiQueueSnapshot,
} from "@posthog/agent/pi/types";
import {
  type AgentConversationEvent,
  type McpToolPermissionDecision,
  type McpToolPermissionRequest,
  type PiRuntimeHealth,
  readMcpInstallationId,
  readMcpToolDescriptor,
  type StoredLogEntry,
  type TaskRunStatus,
} from "@posthog/shared";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import type { CloudTaskClient } from "../cloud-task/cloudTaskClient";
import {
  isTerminalStatus,
  progressNotificationParams,
} from "../cloud-task/schemas";
import type {
  PiConversationEventContext,
  PiSession,
} from "./piSessionController";

function createTerminalPiRpcClient(
  runId: string,
  getRunStatus: () => TaskRunStatus,
  persistedConfig?: PiPersistedSessionConfig | null,
): PiRemoteRpcClient {
  const rejectCommand = async (): Promise<never> => {
    throw new Error(`Cloud task run ${runId} is ${getRunStatus()}`);
  };

  return {
    prompt: rejectCommand,
    steer: rejectCommand,
    followUp: rejectCommand,
    abort: rejectCommand,
    getState: async () => ({
      isStreaming: false,
      isCompacting: false,
      thinkingLevel: persistedConfig?.thinkingLevel ?? "off",
      steeringMode: "all",
      followUpMode: "all",
      sessionId: runId,
      autoCompactionEnabled: true,
      messageCount: 0,
      pendingMessageCount: 0,
    }),
    getSessionStats: rejectCommand,
    setModel: rejectCommand,
    getAvailableModels: async () => [],
    getAvailableThinkingLevels: async () => [],
    setThinkingLevel: rejectCommand,
    compact: rejectCommand,
    bash: rejectCommand,
    abortBash: rejectCommand,
    getEntries: async () => ({ entries: [], leafId: null }),
    getCommands: async () => [],
  };
}

function permissionDescription(
  content: unknown[] | undefined,
): string | undefined {
  for (const item of content ?? []) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const block = item as { type?: unknown; content?: unknown };
    if (block.type !== "content" || !block.content) {
      continue;
    }
    if (typeof block.content !== "object") {
      continue;
    }
    const text = block.content as { type?: unknown; text?: unknown };
    if (text.type === "text" && typeof text.text === "string") {
      return text.text;
    }
  }
  return undefined;
}

export interface CloudPiSessionContext {
  taskId: string;
  runId: string;
  runStatus: TaskRunStatus;
  apiHost: string;
  teamId: number;
  persistedConfig?: PiPersistedSessionConfig | null;
}

export class CloudPiSessionClient implements PiSession {
  private readonly liveClient: PiRemoteRpcClient;
  private readonly terminalClient: PiRemoteRpcClient;
  private runStatus: TaskRunStatus;
  private snapshotEvents: AgentConversationEvent[] = [];
  private snapshotReady = false;
  private resolveSnapshot: () => void = () => {};
  private rejectSnapshot: (error: unknown) => void = () => {};
  private readonly snapshotReceived = new Promise<void>((resolve, reject) => {
    this.resolveSnapshot = resolve;
    this.rejectSnapshot = reject;
  });
  private runtimeReady = false;
  private resolveRuntimeReady: () => void = () => {};
  private rejectRuntimeReady: (error: unknown) => void = () => {};
  private readonly runtimeReadyReceived = new Promise<void>(
    (resolve, reject) => {
      this.resolveRuntimeReady = resolve;
      this.rejectRuntimeReady = reject;
    },
  );
  private terminalEventSent = false;
  private resolveTerminalStatus: () => void = () => {};
  private readonly terminalStatusReceived = new Promise<void>((resolve) => {
    this.resolveTerminalStatus = resolve;
  });

  constructor(
    private readonly cloudTaskClient: CloudTaskClient,
    private readonly context: CloudPiSessionContext,
  ) {
    this.runStatus = context.runStatus;
    if (isTerminalStatus(this.runStatus)) {
      this.resolveTerminalStatus();
    }
    void this.snapshotReceived.catch(() => {});
    void this.runtimeReadyReceived.catch(() => {});
    this.liveClient = new RemotePiRpcClient({
      request: (command) => this.request(command),
    });
    this.terminalClient = createTerminalPiRpcClient(
      context.runId,
      () => this.runStatus,
      context.persistedConfig,
    );
  }

  get client(): PiRemoteRpcClient {
    return isTerminalStatus(this.runStatus)
      ? this.terminalClient
      : this.liveClient;
  }

  get resumeRequired(): boolean {
    return isTerminalStatus(this.runStatus);
  }

  get taskRunId(): string {
    return this.context.runId;
  }

  get persistedConfig(): PiPersistedSessionConfig | null | undefined {
    return this.context.persistedConfig;
  }

  get cloudStatus(): TaskRunStatus {
    return this.runStatus;
  }

  async retry(): Promise<void> {
    await this.cloudTaskClient.retry(this.context.taskId, this.context.runId);
  }

  async getQueue(): Promise<PiQueueSnapshot> {
    try {
      return await this.requestQueue("queue_get");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (
        message.includes("Unknown method: queue_get") ||
        message.includes("queue_get is not supported")
      ) {
        return { steering: [], followUp: [] };
      }
      throw error;
    }
  }

  clearQueue(): Promise<PiQueueSnapshot> {
    return this.requestQueue("queue_clear");
  }

  async sendUserMessage(
    type: "prompt" | "steer" | "follow_up",
    message: string,
    artifactIds: string[],
    id: string = globalThis.crypto.randomUUID(),
  ): Promise<void> {
    await this.waitForRuntimeReady();
    const result = await this.cloudTaskClient.sendCommand({
      taskId: this.context.taskId,
      runId: this.context.runId,
      apiHost: this.context.apiHost,
      teamId: this.context.teamId,
      id,
      method: "user_message",
      params: {
        content: message,
        artifact_ids: artifactIds,
        steer: type === "steer",
      },
    });
    if (!result.success) {
      throw new Error(result.error ?? `Pi RPC command failed: ${type}`);
    }
  }

  health(): Promise<PiRuntimeHealth> {
    if (this.runStatus === "in_progress") {
      return Promise.resolve({ state: "streaming" });
    }
    if (isTerminalStatus(this.runStatus)) {
      return Promise.resolve({ state: "cold" });
    }
    return Promise.resolve({ state: "starting" });
  }

  async getConversation(): Promise<AgentConversationEvent[]> {
    await this.snapshotReceived;
    return this.snapshotEvents;
  }

  onMcpToolPermissionRequest(
    onRequest: (request: McpToolPermissionRequest) => void,
    onError: (error: unknown) => void,
  ): () => void {
    return this.cloudTaskClient.subscribe(
      this.context.taskId,
      this.context.runId,
      (update) => {
        if (update.kind !== "permission_request") {
          return;
        }
        const mcp = readMcpToolDescriptor(update.toolCall._meta);
        const installationId = readMcpInstallationId(update.toolCall._meta);
        if (!mcp || !installationId) {
          return;
        }
        const description = permissionDescription(update.toolCall.content);
        onRequest({
          requestId: update.requestId,
          serverName: mcp.server,
          toolName: mcp.tool,
          installationId,
          arguments: update.toolCall.rawInput ?? {},
          ...(description ? { description } : {}),
        });
      },
      onError,
      () => {},
    );
  }

  async respondMcpToolPermission(
    request: McpToolPermissionRequest,
    decision: McpToolPermissionDecision,
  ): Promise<void> {
    const commandId = globalThis.crypto.randomUUID();
    const command: PiMcpPermissionResponseCommand = {
      id: commandId,
      type: "mcp_permission_response",
      requestId: request.requestId,
      decision,
    };
    const result = await this.cloudTaskClient.sendCommand({
      taskId: this.context.taskId,
      id: commandId,
      runId: this.context.runId,
      apiHost: this.context.apiHost,
      teamId: this.context.teamId,
      method: "pi/rpc",
      params: { command },
    });
    if (!result.success) {
      throw new Error(result.error ?? "MCP permission response failed");
    }
  }

  onConversationEvent(
    onEvent: (
      event: AgentConversationEvent,
      context?: PiConversationEventContext,
    ) => void,
    onError: (error: unknown) => void,
    onCloudStatus?: (status: TaskRunStatus) => void,
  ): () => void {
    let active = true;
    const unsubscribe = this.cloudTaskClient.subscribe(
      this.context.taskId,
      this.context.runId,
      (update) => this.handleUpdate(update, onEvent, onError, onCloudStatus),
      (error) => {
        this.rejectRuntimeReady(error);
        if (!this.snapshotReady || isTerminalStatus(this.runStatus)) {
          this.rejectSnapshot(error);
        }
        onError(error);
      },
      () => {
        if (!active) {
          return;
        }

        void this.cloudTaskClient
          .watch({
            taskId: this.context.taskId,
            runId: this.context.runId,
            apiHost: this.context.apiHost,
            teamId: this.context.teamId,
          })
          .catch((error) => {
            this.rejectRuntimeReady(error);
            if (!this.snapshotReady || isTerminalStatus(this.runStatus)) {
              this.rejectSnapshot(error);
            }
            onError(error);
          });
      },
    );

    return () => {
      active = false;
      unsubscribe();
    };
  }

  private handleUpdate(
    update: CloudTaskUpdatePayload,
    onEvent: (
      event: AgentConversationEvent,
      context?: PiConversationEventContext,
    ) => void,
    onError: (error: unknown) => void,
    onCloudStatus?: (status: TaskRunStatus) => void,
  ): void {
    // A snapshot's historical pi_run_started only proves the runtime is ready
    // to take commands when the sandbox behind it is still alive. On a resume
    // whose sandbox has stopped the sandbox reports dead, so we hold off until a
    // fresh start arrives over the live log stream. The run status fetched when
    // the session opened can lag reality, so trust the snapshot's own signals.
    const snapshotCanProveReadiness =
      update.kind === "snapshot" &&
      update.status === "in_progress" &&
      update.sandboxAlive !== false;
    const hasCurrentReadinessEvent =
      (update.kind === "logs" || snapshotCanProveReadiness) &&
      update.newEntries.some((entry) => entry.type === "pi_run_started");
    if (hasCurrentReadinessEvent) {
      this.markRuntimeReady();
    }

    if (update.kind === "error") {
      const error = Object.assign(new Error(update.errorMessage), {
        title: update.errorTitle,
        retryable: update.retryable,
      });
      this.rejectRuntimeReady(error);
      if (!this.snapshotReady || isTerminalStatus(this.runStatus)) {
        this.rejectSnapshot(error);
      }
      onError(error);
      return;
    }

    if (update.kind === "snapshot") {
      const events = this.getConversationEvents(update.newEntries, 0);
      const previousSourceIds = new Set(
        this.snapshotEvents.flatMap((event) =>
          event.sourceId ? [event.sourceId] : [],
        ),
      );

      this.snapshotEvents = events;
      this.markSnapshotReady();
      for (const event of events) {
        if (!event.sourceId || !previousSourceIds.has(event.sourceId)) {
          onEvent(event, { isLive: false });
        }
      }
    } else if (update.kind === "logs") {
      const firstEntryIndex = update.totalEntryCount - update.newEntries.length;
      const events = this.getConversationEvents(
        update.newEntries,
        firstEntryIndex,
      );
      const existingSourceIds = new Set(
        this.snapshotEvents.flatMap((event) =>
          event.sourceId ? [event.sourceId] : [],
        ),
      );
      const newEvents = events.filter(
        (event) => !event.sourceId || !existingSourceIds.has(event.sourceId),
      );
      this.snapshotEvents = [...this.snapshotEvents, ...newEvents];
      this.markSnapshotReady();
      for (const event of newEvents) {
        onEvent(event, { isLive: true });
      }
    }

    if (
      (update.kind === "snapshot" || update.kind === "status") &&
      update.status
    ) {
      this.runStatus = update.status;
      onCloudStatus?.(update.status);
    }

    if (isTerminalStatus(this.runStatus)) {
      this.resolveTerminalStatus();
      if (!this.terminalEventSent) {
        this.terminalEventSent = true;
        const stopReason =
          this.runStatus === "completed"
            ? "end_turn"
            : this.runStatus === "cancelled"
              ? "cancelled"
              : "failed";
        onEvent(
          { type: "turn_completed", timestamp: Date.now(), stopReason },
          { isLive: update.kind === "status" },
        );
      }
    }

    if (
      this.runStatus === "failed" &&
      (update.kind === "snapshot" || update.kind === "status") &&
      update.errorMessage
    ) {
      onError(
        Object.assign(new Error(update.errorMessage), {
          title: "Cloud run failed",
          retryable: true,
        }),
      );
    }
  }

  private getConversationEvents(
    entries: StoredLogEntry[],
    firstEntryIndex: number,
  ): AgentConversationEvent[] {
    const events: AgentConversationEvent[] = [];
    for (const [index, entry] of entries.entries()) {
      const sourceId =
        entry.id ?? `${this.context.runId}:log:${firstEntryIndex + index}`;
      if (entry.type === "pi_event" && entry.event) {
        events.push({
          ...this.normalizeLegacyEvent(entry.event),
          sourceId,
        });
        continue;
      }

      const progress = this.getProgressEvent(entry);
      if (progress) {
        events.push({ ...progress, sourceId });
      }
    }
    return events;
  }

  private normalizeLegacyEvent(
    event: AgentConversationEvent,
  ): AgentConversationEvent {
    if (
      event.type === "tool_call_started" &&
      event.toolCall.origin === undefined &&
      event.toolCall.id.startsWith("pi-bash-")
    ) {
      return {
        ...event,
        toolCall: { ...event.toolCall, origin: "user_shell" },
      };
    }
    if (
      event.type === "tool_call_updated" &&
      event.toolCall.origin === undefined &&
      event.toolCall.id.startsWith("pi-bash-")
    ) {
      return {
        ...event,
        toolCall: { ...event.toolCall, origin: "user_shell" },
      };
    }
    return event;
  }

  private getProgressEvent(
    entry: StoredLogEntry,
  ): AgentConversationEvent | null {
    if (
      entry.notification?.method !== "_posthog/progress" &&
      entry.notification?.method !== "__posthog/progress"
    ) {
      return null;
    }

    const params = progressNotificationParams.safeParse(
      entry.notification.params,
    );
    const timestamp = Date.parse(entry.timestamp ?? "");
    if (!params.success || Number.isNaN(timestamp)) {
      return null;
    }

    return {
      type: "progress",
      timestamp,
      ...params.data,
    };
  }

  private async requestQueue(
    method: "queue_get" | "queue_clear",
  ): Promise<PiQueueSnapshot> {
    await this.waitForRuntimeReady();
    if (isTerminalStatus(this.runStatus)) {
      return { steering: [], followUp: [] };
    }
    const result = await this.cloudTaskClient.sendCommand({
      taskId: this.context.taskId,
      runId: this.context.runId,
      apiHost: this.context.apiHost,
      teamId: this.context.teamId,
      id: globalThis.crypto.randomUUID(),
      method,
      params: {},
    });
    if (!result.success) {
      throw new Error(result.error ?? `Pi queue command failed: ${method}`);
    }
    return result.result as PiQueueSnapshot;
  }

  private async request(command: RpcCommand): Promise<unknown> {
    await this.waitForRuntimeReady();
    if (isTerminalStatus(this.runStatus)) {
      throw new Error(
        `Cloud task run ${this.context.runId} is ${this.runStatus}`,
      );
    }

    if (!command.id) {
      throw new Error(`Pi RPC command is missing an id: ${command.type}`);
    }

    const isUserMessage =
      command.type === "prompt" ||
      command.type === "steer" ||
      command.type === "follow_up";
    if (isUserMessage) {
      await this.sendUserMessage(command.type, command.message, [], command.id);
      return {
        id: command.id,
        type: "response",
        command: command.type,
        success: true,
      };
    }

    const result = await this.cloudTaskClient.sendCommand({
      taskId: this.context.taskId,
      runId: this.context.runId,
      apiHost: this.context.apiHost,
      teamId: this.context.teamId,
      id: command.id,
      method: "pi/rpc",
      params: { command },
    });
    if (isTerminalStatus(this.runStatus) && command.type === "get_state") {
      return {
        id: command.id,
        type: "response",
        command: "get_state",
        success: true,
        data: {
          isStreaming: false,
          isCompacting: false,
          thinkingLevel: this.context.persistedConfig?.thinkingLevel ?? "off",
          steeringMode: "all",
          followUpMode: "all",
          sessionId: this.context.runId,
          autoCompactionEnabled: true,
          messageCount: this.snapshotEvents.length,
          pendingMessageCount: 0,
        },
      };
    }
    if (!result.success) {
      throw new Error(result.error ?? `Pi RPC command failed: ${command.type}`);
    }

    return result.result;
  }

  private markSnapshotReady(): void {
    if (this.snapshotReady) {
      return;
    }
    this.snapshotReady = true;
    this.resolveSnapshot();
  }

  private markRuntimeReady(): void {
    if (this.runtimeReady) {
      return;
    }
    this.runtimeReady = true;
    this.resolveRuntimeReady();
  }

  private async waitForRuntimeReady(): Promise<void> {
    if (this.runtimeReady || isTerminalStatus(this.runStatus)) {
      return;
    }

    await Promise.race([
      this.runtimeReadyReceived,
      this.terminalStatusReceived,
    ]);
  }
}
