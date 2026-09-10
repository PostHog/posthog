import { formatTokens, formatUsd, formatWindow } from "./spendAnalysisFormat";
import type { SpendAnalysisResponse } from "./spendAnalysisTypes";

/** Sanitises a value for safe inclusion in a markdown-table cell whose contents are then
 * fed to an LLM as a prompt.
 *
 * The spend data flows: event property -> backend aggregation -> this prompt -> new task
 * initialPrompt -> agent first turn. The receiving agent has full tool access (Bash, Edit,
 * Write, MCP), so any markdown structure that "escapes" the table row -- newlines, fence
 * markers, top-level headers -- can be read as a fresh instruction block by the agent. We
 * treat tool / model / product names as untrusted (an event property captured by an SDK
 * could carry attacker-influenced content in multi-tenant projects).
 *
 * - Backslash (`\`) MUST be escaped first; otherwise an input like `foo\|bar` becomes
 *   `foo\\|bar` after the pipe escape, which a markdown parser reads as "literal
 *   backslash, literal pipe" -- defeating the pipe escape we just applied. CodeQL's
 *   incomplete-string-escaping rule catches this exact mistake.
 * - Pipe (`|`) is the only character that actually splits a markdown-table cell mid-row.
 * - Carriage return / line feed end the row and let following text look like a fresh
 *   paragraph or header (`\n\n## SYSTEM OVERRIDE` is the canonical injection shape).
 * - Backticks let an attacker open a fenced code block that swallows everything until
 *   the next backtick run.
 *
 * Replacing newlines/backticks with spaces (rather than escaping) keeps the cell readable
 * to a human reviewer while neutralising the structural attack. */
export function escapeTableCell(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/\|/g, "\\|")
    .replace(/[\r\n`]/g, " ");
}

/** The cost-reduction playbook embedded in every analysis task. Kept as a module constant
 * so product can tweak it without unpicking the data-shaping logic, and so its diff in
 * review is the part product can opine on without reading the markdown-table generator.
 *
 * The levers are intentionally model-agnostic and SDK-agnostic so this ages better than
 * the previous version that named specific model tiers. The agent has the actual data and
 * can fill in specifics. */
const PLAYBOOK = `## What to look at

Use this playbook to interpret the numbers above. Apply the levers in order of impact; not every lever applies to every user.

1. **Input tokens are the bill, not the tool calls themselves.** "Avg input" per tool is the context size dragged along on every call. A tool being expensive almost never means the tool itself is expensive. It means there were many calls each carrying a fat context. The biggest lever is conversation length, not which tool gets called: compact aggressively at logical checkpoints, start fresh sessions for unrelated tasks, avoid backtracking ("actually try X instead") because that re-runs all the prior context plus the alternative.

2. **Model choice.** Look at the "By model" table. If most generations are on the most expensive available model, switching the default to a mid-tier model and only escalating for genuinely hard reasoning is often the single biggest dollar saver. The cheapest tier is essentially free per call for routine work (run a test, check git status, grep for a string).

3. **Subagent hygiene.** The Agent / subagent tool typically has a high avg input because subagents inherit a brief plus the tool registry. They're worth their cost when they protect the main conversation from a long exploration; they're not worth it for "read one file" or "grep one pattern". Use the direct tool for those.

4. **No-tool replies.** If the "By tool" table has a "(no tool)" row, that's the model replying with pure text, no action. Some of that is unavoidable (answering a question), some is the model thinking out loud or asking clarifying questions when it could just act. If this share is greater than ~10% of spend, more directive prompts ("Just do X" instead of "What do you think about X?") cut a round-trip per task.

5. **MCP / tool-registry overhead.** Tool calls that route through MCP (or any plugin layer that ships a tool registry on every turn) often show inflated avg input. If the user has many MCP servers enabled, pruning the ones they don't use shrinks the per-call overhead.

## Output

Give me a ranked list of recommendations. For each: what to do, the data point from the tables that motivates it, and a rough sense of the savings opportunity (a percentage of current spend if you can estimate it).
`;

/** Renders the spend data as a compact markdown report for the prefilled task prompt.
 *
 * Kept inline rather than reused for display because the in-banner tables already render
 * the same data with React. The markdown here exists so the *new* task has the numbers
 * in its prompt context without a second API round-trip. */
export function buildAnalysisPrompt(data: SpendAnalysisResponse): string {
  const { summary } = data;
  const windowLabel = formatWindow(summary.date_from, summary.date_to);
  const codeShare =
    summary.total_cost_usd > 0
      ? Math.round((summary.scoped_cost_usd / summary.total_cost_usd) * 100)
      : 0;

  const productRows = data.by_product.items
    .map(
      (r) =>
        `| ${escapeTableCell(r.product ?? "(none)")} | ${r.event_count.toLocaleString()} | ${formatUsd(r.cost_usd)} |`,
    )
    .join("\n");

  const toolRows = data.by_tool.items
    .slice(0, 10)
    .map(
      (r) =>
        `| ${escapeTableCell(r.tool ?? "(no tool)")} | ${r.generation_count.toLocaleString()} | ${formatTokens(r.avg_input_tokens)} | ${formatUsd(r.cost_usd)} |`,
    )
    .join("\n");

  const modelRows = data.by_model.items
    .map(
      (r) =>
        `| ${escapeTableCell(r.model ?? "(unknown)")} | ${r.generation_count.toLocaleString()} | ${formatTokens(r.input_tokens)} | ${formatTokens(r.output_tokens)} | ${formatUsd(r.cost_usd)} |`,
    )
    .join("\n");

  return `Here is my LLM spend in this app for the last ${windowLabel}. Help me understand what's driving the cost and what concrete changes I should make to reduce it.

Work only from the tables below. Do **not** try to query PostHog AI observability or any external data source. The numbers here are everything you have. Rank advice by impact, lead with the biggest lever, and keep each suggestion concrete and actionable.

## My spend

### Summary
- Total spend: ${formatUsd(summary.total_cost_usd)}
- This app's spend: ${formatUsd(summary.scoped_cost_usd)} (${codeShare}% of total)
- Generations: ${summary.scoped_event_count.toLocaleString()}
- Window: ${windowLabel}

### By product
| Product | Events | Cost |
| --- | --- | --- |
${productRows || "| (none) | 0 | $0 |"}

### By tool (this app, top 10)
| Tool | Generations | Avg input | Cost |
| --- | --- | --- | --- |
${toolRows || "| (none) | 0 | 0 | $0 |"}

### By model (this app)
| Model | Generations | Input | Output | Cost |
| --- | --- | --- | --- | --- |
${modelRows || "| (none) | 0 | 0 | 0 | $0 |"}

${PLAYBOOK}`;
}
