import { createContext, useContext } from "react";

/**
 * When true, shared session-update components (notably `ToolRow`) render their chrome with the new
 * ChatX primitives (`ChatMarker`) instead of the legacy Radix chrome. The experimental `ChatThread`
 * turns this on; the production `ConversationView` never provides it, so its rendering is unchanged.
 *
 * This lets one shared `ToolRow` serve both threads — the new thread swaps chrome via context
 * rather than forking every per-tool view.
 */
const ChatThreadChromeContext = createContext(false);

export const ChatThreadChromeProvider = ChatThreadChromeContext.Provider;

export function useChatThreadChrome(): boolean {
  return useContext(ChatThreadChromeContext);
}
