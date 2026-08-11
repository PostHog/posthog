import type { Signal } from "@posthog/shared/domain-types";
import { createContext, useContext } from "react";

export type SignalInteractionAction =
  | { type: "expand_signal" }
  | { type: "collapse_signal" }
  | {
      type: "expand_signal_section";
      section: "relevant_code" | "data_queried";
    }
  | { type: "view_signal_external" }
  | { type: "play_session_recording" };

export interface SignalInteractionContextValue {
  signal: Signal;
  onInteraction: (action: SignalInteractionAction) => void;
}

export const SignalInteractionContext =
  createContext<SignalInteractionContextValue | null>(null);

export function useSignalInteraction(): SignalInteractionContextValue | null {
  return useContext(SignalInteractionContext);
}
