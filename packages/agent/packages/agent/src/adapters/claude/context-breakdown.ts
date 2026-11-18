// Anthropic doesn't break `input_tokens` down by source; we estimate the bits
// we control via a chars-per-token heuristic. Indicative, not invoice-grade.

export type ContextCategory =
  | "systemPrompt"
  | "tools"
  | "rules"
  | "skills"
  | "mcp"
  | "subagents"
  | "conversation";

export type ContextBreakdown = Record<ContextCategory, number>;

// The `claude_code` preset prompt is opaque to us; without this constant its
// tokens would bleed into the Conversation bucket and skew the chart.
const CLAUDE_PRESET_ESTIMATE_TOKENS = 4000;

const CHARS_PER_TOKEN = 4;

export function estimateTokens(text: string | undefined | null): number {
  if (!text) return 0;
  return Math.max(0, Math.round(text.length / CHARS_PER_TOKEN));
}

export function estimateJsonTokens(value: unknown): number {
  try {
    return estimateTokens(JSON.stringify(value));
  } catch {
    return 0;
  }
}

interface SlashCommandLike {
  name?: string;
  description?: string;
  input?: { hint?: string } | null;
}

export function estimateSkillsTokens(commands: SlashCommandLike[]): number {
  if (!commands.length) return 0;
  return estimateJsonTokens(
    commands.map((c) => ({
      name: c.name,
      description: c.description,
      hint: c.input?.hint,
    })),
  );
}

interface McpToolLike {
  name?: string;
  description?: string;
}

// The SDK relies on tool search rather than inlining full MCP schemas in the
// prompt, so name + description is a conservative estimate of what's resident.
export function estimateMcpTokens(tools: McpToolLike[]): number {
  if (!tools.length) return 0;
  return estimateJsonTokens(
    tools.map((t) => ({ name: t.name, description: t.description })),
  );
}

export function estimateRulesTokens(rules: string | undefined): number {
  return estimateTokens(rules);
}

export interface ContextBreakdownBaseline {
  systemPrompt: number;
  tools: number;
  rules: number;
  skills: number;
  mcp: number;
  subagents: number;
}

export function emptyBaseline(): ContextBreakdownBaseline {
  return {
    systemPrompt: 0,
    tools: 0,
    rules: 0,
    skills: 0,
    mcp: 0,
    subagents: 0,
  };
}

export function estimateSystemPrompt(systemPrompt: unknown): number {
  if (!systemPrompt) return CLAUDE_PRESET_ESTIMATE_TOKENS;
  if (typeof systemPrompt === "string") return estimateTokens(systemPrompt);
  if (typeof systemPrompt === "object") {
    const obj = systemPrompt as { type?: string; append?: unknown };
    const appendTokens =
      typeof obj.append === "string" ? estimateTokens(obj.append) : 0;
    if (obj.type === "preset") {
      return CLAUDE_PRESET_ESTIMATE_TOKENS + appendTokens;
    }
    return appendTokens;
  }
  return 0;
}

// Conversation is floored at 0 so estimation drift in the stable categories
// can't surface a negative bucket.
export function buildBreakdown(
  baseline: ContextBreakdownBaseline,
  currentInputTokens: number,
): ContextBreakdown {
  const stableSum =
    baseline.systemPrompt +
    baseline.tools +
    baseline.rules +
    baseline.skills +
    baseline.mcp +
    baseline.subagents;
  const conversation = Math.max(0, currentInputTokens - stableSum);
  return {
    systemPrompt: baseline.systemPrompt,
    tools: baseline.tools,
    rules: baseline.rules,
    skills: baseline.skills,
    mcp: baseline.mcp,
    subagents: baseline.subagents,
    conversation,
  };
}
