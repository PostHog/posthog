import { createContext, useContext } from "react";

/**
 * When true, shared session-update components such as `ToolRow` use ChatMarker chrome. The
 * standalone fallback keeps its existing chrome when this provider is absent, so shared views can
 * render in either context without forking.
 */
const ChatThreadChromeContext = createContext(false);

export const ChatThreadChromeProvider = ChatThreadChromeContext.Provider;

export function useChatThreadChrome(): boolean {
  return useContext(ChatThreadChromeContext);
}
