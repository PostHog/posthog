/** The shared `signals-scout-*` skill-name prefix. It is noise wherever a person reads a scout's name. */
export const SIGNALS_SCOUT_SKILL_PREFIX = "signals-scout-";

/** Strip the fleet prefix, leaving the bare scout code name verbatim. `signals-scout-apm` → `apm`. */
export function stripScoutPrefix(skillName: string): string {
  return skillName.startsWith(SIGNALS_SCOUT_SKILL_PREFIX)
    ? skillName.slice(SIGNALS_SCOUT_SKILL_PREFIX.length)
    : skillName;
}

// Slugs are lowercase, so sentence-casing alone turns `apm` into "Apm".
const WORD_CASING: Record<string, string> = {
  ab: "A/B",
  ai: "AI",
  api: "API",
  apm: "APM",
  aws: "AWS",
  b2b: "B2B",
  cdp: "CDP",
  ci: "CI",
  cpu: "CPU",
  csp: "CSP",
  csv: "CSV",
  cta: "CTA",
  dau: "DAU",
  github: "GitHub",
  gcp: "GCP",
  hogql: "HogQL",
  http: "HTTP",
  id: "ID",
  json: "JSON",
  kpi: "KPI",
  llm: "LLM",
  mau: "MAU",
  mcp: "MCP",
  mrr: "MRR",
  nps: "NPS",
  posthog: "PostHog",
  pr: "PR",
  qa: "QA",
  rag: "RAG",
  sdk: "SDK",
  seo: "SEO",
  sla: "SLA",
  sql: "SQL",
  ui: "UI",
  url: "URL",
  utm: "UTM",
  ux: "UX",
};

/**
 * The fallback name for a scout with no display name: `signals-scout-mcp-tool-calls` → "MCP tool calls".
 * Prefer `scoutDisplayName` whenever the scout's config is at hand.
 */
export function prettifyScoutSkillName(skillName: string): string {
  const words = stripScoutPrefix(skillName)
    .split(/[-_\s]+/)
    .filter(Boolean);
  if (words.length === 0) {
    return skillName;
  }
  const cased = words.map(
    (word) => WORD_CASING[word.toLowerCase()] ?? word.toLowerCase(),
  );
  return cased[0].charAt(0).toUpperCase() + cased.join(" ").slice(1);
}

export interface ScoutNameSource {
  skill_name: string;
  display_name?: string | null;
}

/** The name a person reads for a scout: the team's display name, else the prettified skill name. */
export function scoutDisplayName(config: ScoutNameSource): string {
  return (
    config.display_name?.trim() || prettifyScoutSkillName(config.skill_name)
  );
}

/** A scout's name as a noun phrase, "APM scout", without doubling a name that already ends in "scout". */
export function withScoutNoun(name: string): string {
  return /\bscout$/i.test(name) ? name : `${name} scout`;
}

/** Display names keyed by skill name, for surfaces that only hold a scout's skill name. */
export function scoutNamesBySkill(
  configs: readonly ScoutNameSource[] | null | undefined,
): Record<string, string> {
  const names: Record<string, string> = {};
  for (const config of configs ?? []) {
    names[config.skill_name] = scoutDisplayName(config);
  }
  return names;
}

/** Resolve a skill name through a `scoutNamesBySkill` map. A scout with no config (deleted, or not
 * loaded yet) falls back to its prettified skill name. */
export function scoutNameForSkill(
  names: Readonly<Record<string, string>> | null | undefined,
  skillName: string,
): string {
  return names?.[skillName] ?? prettifyScoutSkillName(skillName);
}
