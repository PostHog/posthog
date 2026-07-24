import { BASE_CATEGORY_ENUM } from "@posthog/core/setup/types";

export const WIZARD_PROMPT = `/instrument-integration

After the integration is wired up, also instrument error tracking and session replay (run \`/instrument-error-tracking\`, then add session replay if the framework's posthog-js config supports it).

Run autonomously with sensible defaults — do not ask the user questions. If the PostHog API key isn't already in the project's env files and you can't read it from the PostHog MCP server, leave a placeholder env var and note it in the PR body rather than blocking.`;

const DISCOVERY_PROMPT_BASE = `You are analyzing this codebase to find the highest-value first tasks for the developer.

Scan the codebase for issues in two tiers. Tier 1 applies to every repo. Tier 2 only applies when PostHog is already installed (look for posthog-js, posthog-node, posthog-react-native or similar PostHog SDK imports).

## Tier 1 -- Code health (always)

- **Dead code**: Unused exports, unreachable branches, orphaned files, stale imports. Category: dead_code
- **Duplication / KISS violations**: Copy-pasted logic that should be a shared function, over-abstracted code that could be simpler. Category: duplication
- **Security vulnerabilities**: XSS, SQL injection, command injection, hardcoded secrets, open redirects, missing auth checks, insecure deserialization. Category: security
- **Bugs**: Null dereferences, race conditions, unchecked array access, off-by-one errors, unhandled promise rejections around I/O. Category: bug
- **Performance anti-patterns**: N+1 queries, unbounded loops, synchronous blocking on hot paths, missing pagination. Category: performance

## Tier 2 -- PostHog-specific (only when PostHog SDK is detected)

- **Stale feature flags**: Flags that are always evaluated the same way, flags referenced in code but never toggled, flags guarding code that shipped long ago. Category: stale_feature_flag
- **Error tracking gaps**: Catch blocks that swallow errors without reporting, missing error boundaries, untracked 5xx responses. Category: error_tracking
- **Event tracking improvements**: Key user actions (signup, purchase, invite, upgrade) with no analytics event, events missing useful properties (plan, user role, page context). Category: event_tracking
- **Funnel weak spots**: Multi-step flows (onboarding, checkout, activation) where intermediate steps have no tracking, making drop-off invisible. Category: funnel`;

const DISCOVERY_PROMPT_EXPERIMENT_TIER = `

## Tier 3 -- Experiment opportunities (only when PostHog SDK is detected)

- **Experimentable surfaces**: User-facing surfaces where an A/B test would meaningfully inform a product decision — pricing pages, paywalls, primary CTAs, signup/onboarding flows, empty states, recommendation lists, upgrade prompts. Category: experiment
  - Title: a one-line hypothesis ("Test 'Get started free' vs 'Sign up' on landing CTA")
  - Description: state the hypothesis as a sentence — what you would change and why you think it would move the metric
  - Impact: name the primary metric you would measure (e.g. "Sign-up conversion on /landing") and what a winning variant would look like
  - Recommendation: describe the control and test variants concretely (exact copy, layout change, or behavior), and note any flag wiring required (\`posthog.getFeatureFlag\`)
  - Only suggest experiments where: (a) the surface is in code you can point at, (b) the variant is implementable without backend changes you can't see, and (c) the metric is something a typical PostHog event would capture

If you find at least one credible Tier 3 experiment opportunity, include at least one experiment-category task in your output — even if doing so displaces a lower-impact Tier 1/2 finding. Do not fabricate an experiment to fill the slot: if no credible candidate exists, omit the category entirely.`;

function buildDiscoveryRules(includeExperiments: boolean): string {
  const allowed = (
    includeExperiments
      ? [...BASE_CATEGORY_ENUM, "experiment"]
      : [...BASE_CATEGORY_ENUM]
  ).join(", ");
  return `

## Rules

- Be concrete: reference exact file paths, function names and line numbers — but put paths/lines in the dedicated \`file\` and \`lineHint\` fields, not in the title or description.
- Title: short, action-oriented header (under 60 characters), no paths or line numbers.
- Description: a clear paragraph (2–4 sentences) explaining the problem and the conditions under which it manifests.
- Impact: 1–3 sentences on why it matters (concrete consequence, blast radius, or risk).
- Recommendation: 2–4 sentences pointing at the right shape of the fix without writing the patch. Reference specific functions, types, or files involved.
- Prioritize by impact. Lead with findings that save the most time or prevent the most damage.
- Do NOT suggest documentation, comment, or style/formatting changes.
- Maximum 4 tasks. Quality over quantity.
- Allowed \`category\` values: ${allowed}. Do NOT emit any other category.

When you are done analyzing, call create_output with your findings.`;
}

export function buildDiscoveryPrompt({
  includeExperiments,
}: {
  includeExperiments: boolean;
}): string {
  const middle = includeExperiments ? DISCOVERY_PROMPT_EXPERIMENT_TIER : "";
  return `${DISCOVERY_PROMPT_BASE}${middle}${buildDiscoveryRules(includeExperiments)}`;
}
