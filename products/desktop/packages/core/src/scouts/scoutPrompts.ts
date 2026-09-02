// Templated prompts behind the scout chat CTA chips. The agent leans on the
// exploring-signals-scouts and authoring-signals-scouts skills from the
// PostHog MCP.

export const SCOUT_AUTHOR_PROMPT = `I'd like to make a new scout for this PostHog project.

Use the authoring-signals-scouts skill from the PostHog MCP to guide creating a new signals scout.

First, take a quick scan of this PostHog project to ground your suggestions: skim its events, insights, dashboards, recently emitted signals, and the existing scout fleet so you understand what this product is and where automated monitoring would add value.

Then ask me what sort of scout I'd like to make, and offer a few concrete suggestions tailored to what you found (for example specific funnels, error or latency spikes, churn or activation signals, or revenue metrics worth watching) — and call out gaps the current fleet doesn't already cover. Once I pick a direction, walk me through authoring the scout end to end.

If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list to see the existing fleet) plus the read-data and insight tools to scan the project.`;

export const SCOUT_FLEET_OVERVIEW_PROMPT = `How is my scout fleet performing?

Use the exploring-signals-scouts skill from the PostHog MCP to survey the signals scout fleet on this project and give me a high-level overview:

- The fleet: which scouts exist, enabled vs disabled, and their cadences
- Recent run health: success rate, failures and timeouts, anything stuck
- Output: which scouts emitted signals recently, emit rate, signal-to-noise
- Memory: notable scratchpad entries the fleet has learned
- Recommendations: anything misconfigured, noisy, or worth tuning

Lead with a short overall verdict, then per-scout notes only where something is notable. If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list, runs list, scratchpad search).`;

export const SCOUT_RECENT_SIGNALS_PROMPT = `What signals have my scouts emitted recently?

Use the exploring-signals-scouts skill from the PostHog MCP to pull the most recent scout runs that emitted findings and walk me through the signals:

- What each signal says, in plain language
- Which scout emitted it, when, and its severity/confidence where available
- Whether it looks genuinely actionable or like noise

Group by scout, newest first. Close with a short note on overall signal quality and any scouts that look noisy or suspiciously silent. If the skill is unavailable, fall back to the signals-scout MCP tools directly (runs list with emitted filter, run emissions).`;

/**
 * Templated prompt for digging into a single finding a scout emitted, scoped to
 * that finding plus an optional free-text question the user typed before kicking
 * the task off (mirrors the inbox report Discuss flow).
 */
export function buildScoutFindingDiscussPrompt({
  skillName,
  displayName,
  runId,
  findingId,
  description,
  severity,
  confidence,
  question,
}: {
  skillName: string;
  displayName: string;
  runId: string;
  findingId: string;
  description: string;
  severity: string | null;
  confidence: number;
  question?: string;
}): string {
  const trimmedQuestion = question?.trim();
  const meta = [
    `Scout: \`${skillName}\` (${displayName})`,
    `Run ID: ${runId}`,
    `Finding ID: ${findingId}`,
    severity ? `Severity: ${severity}` : null,
    `Confidence: ${Math.round(confidence * 100)}%`,
  ]
    .filter(Boolean)
    .join("\n");

  return `I want to dig into a specific finding my ${displayName} scout emitted and work out whether it needs action.

${meta}

Finding:
${description}

${
  trimmedQuestion
    ? `Answer this first: ${trimmedQuestion}`
    : "Give me a brief readout on what this finding means and whether it looks genuinely actionable or like noise, then ask what I want to dig into."
}

Use the exploring-signals-scouts skill from the PostHog MCP to ground your investigation: fetch this exact run's emissions (run ${runId}) for the finding's full context, pull the \`${skillName}\` scout's recent runs, cross-reference the relevant product data, and assess whether it's real and worth acting on. If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list, runs list, run emissions) plus the read-data and insight tools.`;
}

/** Per-scout variant of the templated questions, scoped to one skill. */
export function buildScoutCheckinPrompt(
  skillName: string,
  displayName: string,
): string {
  return `How is my ${displayName} scout performing?

Use the exploring-signals-scouts skill from the PostHog MCP to dig into the \`${skillName}\` scout on this project:

- Its config: enabled, cadence, dry-run posture
- Recent run history: successes, failures, timeouts, durations
- Signals it emitted recently and whether they look genuinely actionable
- Scratchpad memory the fleet holds that relates to this scout
- Whether its scope, thresholds, and schedule look right – suggest tuning if not

Lead with a short verdict. If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list, runs list, run emissions, scratchpad search).`;
}
