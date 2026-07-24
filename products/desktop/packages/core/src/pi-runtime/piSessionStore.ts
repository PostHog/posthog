import type {
  PiCommand,
  PiModelOption,
  PiSessionStatus,
} from "@posthog/agent/pi/types";
import type { AgentConversationEvent } from "@posthog/shared";
import { createStore, type StoreApi } from "zustand/vanilla";

export interface PiControllerSessionState {
  connectionState: "connecting" | "connected" | "failed";
  events: AgentConversationEvent[];
  models: PiModelOption[];
  commands: PiCommand[];
  status?: PiSessionStatus;
  error?: string;
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
    commands: [],
    isBashRunning: false,
  };
}
