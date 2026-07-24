import { useEffect } from "react";
import {
  type AgentBuilderPageContext,
  useAgentBuilderStore,
} from "./agentBuilderStore";

/**
 * Registers what the user is currently looking at so the agent builder can resolve
 * deictic references and drive the right `focus_*` target. Each `/code/agents`
 * route calls this on mount. No cleanup: the next route overwrites the page, so
 * the last-viewed context persists (the dock only reads it inside `/code/agents`).
 */
export function useSetAgentBuilderPage(page: AgentBuilderPageContext): void {
  const setPage = useAgentBuilderStore((s) => s.setPage);
  const key = JSON.stringify(page);
  useEffect(() => {
    setPage(JSON.parse(key) as AgentBuilderPageContext);
  }, [key, setPage]);
}
