import type {
  PiCommand,
  PiNativeModelInfo,
  PiQueueSnapshot,
  PiSessionStats,
  PiSessionStatus,
  PiThinkingLevel,
} from "@posthog/agent/pi/types";
import type {
  AgentConversationEvent,
  GatewayLimitCause,
  PromptFailureKind,
  SessionStatus,
  TaskRunStatus,
} from "@posthog/shared";
import { createStore, type StoreApi } from "zustand/vanilla";

export interface PiSessionError {
  id: string;
  scope: "connection" | "operation";
  kind: PromptFailureKind;
  title: string;
  message: string;
  retryable: boolean;
  limitCause: GatewayLimitCause | null;
  recoveryPrompt?: string;
}

export interface PiControllerSessionState {
  connectionState: SessionStatus;
  events: AgentConversationEvent[];
  models: Array<Pick<PiNativeModelInfo, "provider" | "id">>;
  modelsLoaded: boolean;
  thinkingLevels: PiThinkingLevel[];
  thinkingLevelsLoaded: boolean;
  commands: PiCommand[];
  queue: PiQueueSnapshot;
  status?: PiSessionStatus;
  stats?: PiSessionStats;
  cloudStatus?: TaskRunStatus;
  error?: PiSessionError;
  authRestoring: boolean;
  isBashRunning: boolean;
}

export interface PiSessionState {
  sessions: Record<string, PiControllerSessionState>;
}

export type PiSessionStore = StoreApi<PiSessionState>;

export function createPiSessionStore(): PiSessionStore {
  return createStore<PiSessionState>(() => ({ sessions: {} }));
}

export function createEmptyPiControllerSession(): PiControllerSessionState {
  return {
    connectionState: "connecting",
    events: [],
    models: [],
    modelsLoaded: false,
    thinkingLevels: [],
    thinkingLevelsLoaded: false,
    commands: [],
    queue: { steering: [], followUp: [] },
    authRestoring: false,
    isBashRunning: false,
  };
}
