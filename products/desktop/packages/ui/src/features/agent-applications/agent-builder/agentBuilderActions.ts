import type { AgentBuilderPageContext } from "./agentBuilderStore";

export interface AgentBuilderAction {
  /** Short button label, e.g. "New agent" / "Explain this session". */
  label: string;
  /** Seed prompt sent to the agent builder when clicked. */
  prompt: string;
  /** Subject agent for the context envelope (null for fleet-level actions). */
  agentSlug: string | null;
}

/**
 * The contextual agent-builder action for a given view — the AI button's
 * content. Drives the abstract header controls so every agents view gets a
 * button that fits what you're looking at. Returns null for views with no
 * obvious action (just the show/following affordances remain).
 */
export function headerActionForPage(
  page: AgentBuilderPageContext,
): AgentBuilderAction | null {
  switch (page.kind) {
    case "agent-list":
      return {
        label: "New agent",
        prompt:
          "Help me create a new agent — walk me through what it should do, then set it up.",
        agentSlug: null,
      };
    case "agent":
      return {
        label: "Explain this agent",
        prompt: "Explain what this agent does and how it's configured.",
        agentSlug: page.slug,
      };
    case "agent-config":
      return {
        label: "Edit configuration",
        prompt: "Help me change this agent's configuration.",
        agentSlug: page.slug,
      };
    case "agent-sessions":
      return {
        label: "Review sessions",
        prompt:
          "Review this agent's recent sessions and surface anything notable.",
        agentSlug: page.slug,
      };
    case "agent-session":
      return {
        label: "Explain this session",
        prompt: "Explain what happened in this session, step by step.",
        agentSlug: page.slug,
      };
    case "agent-approvals":
      return {
        label: "Review approvals",
        prompt: "Review the pending approval requests for this agent.",
        agentSlug: page.slug,
      };
    case "agent-memory":
      return {
        label: "Ask about memory",
        prompt: "Summarize what's stored in this agent's memory.",
        agentSlug: page.slug,
      };
    case "agent-observability":
      return {
        label: "Ask about performance",
        prompt:
          "Summarize this agent's spend, volume, and failure rate, and call out anything notable.",
        agentSlug: page.slug,
      };
    default:
      return null;
  }
}
