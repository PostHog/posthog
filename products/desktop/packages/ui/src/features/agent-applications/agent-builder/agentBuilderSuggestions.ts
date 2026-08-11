import type { AgentBuilderPageContext } from "./agentBuilderStore";

export interface AgentBuilderSuggestion {
  label: string;
  prompt: string;
}

/**
 * Starter prompts shown in the empty Agent Builder dock, tailored to what the
 * user is looking at. The agent resolves "this agent"/"this session" from the
 * page-context envelope, so prompts can stay deictic. Mirrors the old console's
 * contextual suggestions.
 */
export function suggestionsForPage(
  page: AgentBuilderPageContext,
): AgentBuilderSuggestion[] {
  switch (page.kind) {
    case "agent-list":
    case "scouts":
    case "unknown":
      return [
        {
          label: "Create a new agent",
          prompt:
            "Help me create a new agent — walk me through what it should do, then set it up.",
        },
        {
          label: "What's changed in the last week?",
          prompt:
            "Summarize what's changed across my agents in the last week — new revisions, notable sessions, and any failures.",
        },
        {
          label: "Audit my agents",
          prompt:
            "Audit all my agents and flag anything underperforming or misconfigured.",
        },
      ];
    case "agent":
      return [
        {
          label: "What does this agent do?",
          prompt: "Explain what this agent does and how it's configured.",
        },
        {
          label: "Is this agent healthy?",
          prompt:
            "Check this agent's recent sessions and tell me whether it's healthy.",
        },
        {
          label: "Suggest improvements",
          prompt: "Review this agent and suggest concrete improvements.",
        },
      ];
    case "agent-config":
      return [
        {
          label: "Explain this configuration",
          prompt: "Walk me through this agent's configuration.",
        },
        {
          label: "Edit the system prompt",
          prompt: "I want to change this agent's system prompt.",
        },
        {
          label: "Add a tool or skill",
          prompt: "Help me add a tool or skill to this agent.",
        },
      ];
    case "agent-sessions":
      return [
        {
          label: "Any failing sessions?",
          prompt:
            "Look at this agent's recent sessions and surface any failures.",
        },
        {
          label: "Summarize recent activity",
          prompt: "Summarize this agent's recent session activity.",
        },
      ];
    case "agent-session":
      return [
        {
          label: "What happened here?",
          prompt: "Explain what happened in this session, step by step.",
        },
        {
          label: "Debug this session",
          prompt: "Debug this session — what went wrong and how do I fix it?",
        },
      ];
    case "agent-approvals":
      return [
        {
          label: "Review pending approvals",
          prompt: "Review the pending approval requests for this agent.",
        },
      ];
    case "agent-memory":
      return [
        {
          label: "What's in memory?",
          prompt: "Summarize what's stored in this agent's memory.",
        },
      ];
    case "agent-observability":
      return [
        {
          label: "How is this agent performing?",
          prompt:
            "Summarize this agent's spend, volume, and failure rate, and call out anything notable.",
        },
      ];
    default:
      return [
        {
          label: "Create a new agent",
          prompt: "Help me create a new agent.",
        },
        {
          label: "What's changed in the last week?",
          prompt: "Summarize what's changed across my agents in the last week.",
        },
      ];
  }
}
