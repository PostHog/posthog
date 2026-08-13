import type { EnrichedEvent, EnrichedFlag, EnrichedListItem } from "./types.js";

function commentPrefix(languageId: string): string {
  if (languageId === "python" || languageId === "ruby") {
    return "#";
  }
  return "//";
}

function formatFlagComment(flag: EnrichedFlag): string {
  const parts: string[] = [`Flag: "${flag.flagKey}"`];

  if (!flag.flag) {
    parts.push("not in PostHog");
    return parts.join(" \u2014 ");
  }

  parts.push(flag.flagType);
  parts.push(flag.flag.active ? "active" : "inactive");
  if (flag.rollout !== null) {
    parts.push(`${flag.rollout}% rolled out`);
  }
  if (flag.evaluationStats) {
    const evals = flag.evaluationStats.evaluations.toLocaleString();
    const users = flag.evaluationStats.uniqueUsers.toLocaleString();
    const days = flag.evaluationStats.windowDays;
    parts.push(`${evals} evals / ${users} users (${days}d)`);
  } else if (flag.evaluationStatsError) {
    parts.push("eval stats unavailable");
  }
  if (flag.experiment) {
    const status = flag.experiment.end_date ? "complete" : "running";
    parts.push(`Experiment: "${flag.experiment.name}" (${status})`);
  }
  if (flag.staleness) {
    parts.push(`STALE (${flag.staleness})`);
  }
  if (flag.url) {
    parts.push(flag.url);
  }

  return parts.join(" \u2014 ");
}

function formatEventComment(event: EnrichedEvent): string {
  const parts: string[] = [`Event: "${event.eventName}"`];
  if (event.verified) {
    parts.push("(verified)");
  }
  if (event.stats?.volume !== undefined) {
    parts.push(`${event.stats.volume.toLocaleString()} events`);
  }
  if (event.stats?.uniqueUsers !== undefined) {
    parts.push(`${event.stats.uniqueUsers.toLocaleString()} users`);
  }
  if (event.definition?.description) {
    parts.push(event.definition.description);
  }
  return parts.join(" \u2014 ");
}

function buildCommentBody(
  item: EnrichedListItem,
  enrichedFlags: Map<string, EnrichedFlag>,
  enrichedEvents: Map<string, EnrichedEvent>,
): string | null {
  let body: string | null = null;
  if (item.type === "flag") {
    const flag = enrichedFlags.get(item.name);
    body = flag ? formatFlagComment(flag) : null;
  } else if (item.type === "event") {
    const event = enrichedEvents.get(item.name);
    if (event) {
      body = formatEventComment(event);
    } else if (item.detail) {
      body = `Event: ${item.detail}`;
    }
  } else if (item.type === "init") {
    body = `Init: token "${item.name}"`;
  }

  if (!body) return null;
  if (item.viaWrapper) {
    body = `${body} (via ${item.viaWrapper})`;
  }
  return body;
}

export function formatComments(
  source: string,
  languageId: string,
  items: EnrichedListItem[],
  enrichedFlags: Map<string, EnrichedFlag>,
  enrichedEvents: Map<string, EnrichedEvent>,
): string {
  const prefix = commentPrefix(languageId);
  const lines = source.split("\n");
  const sorted = [...items].sort((a, b) => a.line - b.line);

  let offset = 0;

  for (const item of sorted) {
    const targetLine = item.line + offset;
    const body = buildCommentBody(item, enrichedFlags, enrichedEvents);
    if (!body) continue;

    const comment = item.inJsx
      ? `{/* [PostHog] ${body} */}`
      : `${prefix} [PostHog] ${body}`;
    const indent = lines[targetLine]?.match(/^(\s*)/)?.[1] ?? "";
    lines.splice(targetLine, 0, `${indent}${comment}`);
    offset++;
  }

  return lines.join("\n");
}

export function formatInlineComments(
  source: string,
  languageId: string,
  items: EnrichedListItem[],
  enrichedFlags: Map<string, EnrichedFlag>,
  enrichedEvents: Map<string, EnrichedEvent>,
): string {
  const prefix = commentPrefix(languageId);
  const lines = source.split("\n");
  // Per line, separate bodies by JSX vs JS context. Inline suffixes use
  // different comment syntax in each context, so we can't safely coalesce
  // mixed-context items into a single inline suffix.
  const byLine = new Map<
    number,
    { jsxBodies: string[]; nonJsxBodies: string[] }
  >();

  for (const item of items) {
    const body = buildCommentBody(item, enrichedFlags, enrichedEvents);
    if (!body) continue;
    const entry = byLine.get(item.line) ?? { jsxBodies: [], nonJsxBodies: [] };
    (item.inJsx ? entry.jsxBodies : entry.nonJsxBodies).push(body);
    byLine.set(item.line, entry);
  }

  // When a single line mixes JSX and JS items we can't append one inline
  // suffix without risking invalid syntax in one context or the other, so
  // fall back to a JSX-style leading comment (valid as both an empty-block
  // statement in JS and a JSX expression comment in JSX trees).
  const leadingInserts: Array<{ atLine: number; text: string }> = [];

  for (const [lineIdx, { jsxBodies, nonJsxBodies }] of byLine) {
    if (lineIdx < 0 || lineIdx >= lines.length) continue;

    if (jsxBodies.length > 0 && nonJsxBodies.length > 0) {
      const joined = [...nonJsxBodies, ...jsxBodies].join(" | ");
      const indent = lines[lineIdx]?.match(/^(\s*)/)?.[1] ?? "";
      leadingInserts.push({
        atLine: lineIdx,
        text: `${indent}{/* [PostHog] ${joined} */}`,
      });
      continue;
    }

    const isJsx = jsxBodies.length > 0;
    const bodies = isJsx ? jsxBodies : nonJsxBodies;
    const joined = bodies.join(" | ");
    const suffix = isJsx
      ? ` {/* [PostHog] ${joined} */}`
      : ` ${prefix} [PostHog] ${joined}`;
    lines[lineIdx] = `${lines[lineIdx]}${suffix}`;
  }

  leadingInserts.sort((a, b) => b.atLine - a.atLine);
  for (const { atLine, text } of leadingInserts) {
    lines.splice(atLine, 0, text);
  }

  return lines.join("\n");
}
