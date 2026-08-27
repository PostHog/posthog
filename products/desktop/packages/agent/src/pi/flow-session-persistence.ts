import type { AgentSession } from "@earendil-works/pi-coding-agent";
import { AGENT_FLOW_MESSAGE_TYPE } from "@posthog/shared";

interface FlushableSessionManager {
  flushed: boolean;
  _rewriteFile(): void;
}

type SubscribableSession = Pick<AgentSession, "subscribe"> & {
  sessionManager: unknown;
};

// Pi persists a session file only after an assistant message; a flow has none.
export function persistAgentFlowSessions(session: SubscribableSession): void {
  const sessionManager = session.sessionManager as FlushableSessionManager;
  session.subscribe((event) => {
    if (
      event.type !== "message_end" ||
      event.message.role !== "custom" ||
      event.message.customType !== AGENT_FLOW_MESSAGE_TYPE ||
      sessionManager.flushed
    ) {
      return;
    }
    sessionManager._rewriteFile();
    sessionManager.flushed = true;
  });
}
