import type {
  PiCommand,
  PiExtensionUIRequest,
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

export type PiExtensionDialogRequest = Extract<
  PiExtensionUIRequest,
  { method: "select" | "confirm" | "input" | "editor" }
>;

export interface PiExtensionNotification {
  id: string;
  message: string;
  notifyType: "info" | "warning" | "error";
}

export interface PiExtensionWidget {
  lines: string[];
  placement: "aboveEditor" | "belowEditor";
}

export interface PiExtensionEditorText {
  id: string;
  text: string;
}

export interface PiProjectTrustState {
  trusted: boolean;
  hasProjectResources: boolean;
}

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
  projectTrust?: PiProjectTrustState;
  extensionDialogs: PiExtensionDialogRequest[];
  extensionNotifications: PiExtensionNotification[];
  extensionStatuses: Record<string, string>;
  extensionWidgets: Record<string, PiExtensionWidget>;
  extensionTitle?: string;
  extensionEditorText?: PiExtensionEditorText;
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
    extensionDialogs: [],
    extensionNotifications: [],
    extensionStatuses: {},
    extensionWidgets: {},
  };
}
