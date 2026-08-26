import type { AgentSession } from "@earendil-works/pi-coding-agent";
import { AGENT_FLOW_MESSAGE_TYPE } from "@posthog/shared";

interface FlushableSessionManager {
  flushed: boolean;
  _rewriteFile(): void;
}

type SubscribableSession = Pick<AgentSession, "subscribe"> & {
  sessionManager: unknown;
};

/**
 * Pi writes a session file only once the session has an assistant message.
 * An agent flow runs entirely in subagent child processes, so its session
 * holds only custom messages and would never persist: the transcript dies
 * with the rpc host. Flush the session file on the first flow message so
 * reopening the task after a restart still shows the flow.
 */
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
