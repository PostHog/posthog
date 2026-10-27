import type { UserClaudeIntegration } from "@posthog/api-client/posthog-client";
import { isValidClaudeSetupToken } from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";

const DAY_MS = 24 * 60 * 60 * 1000;
const TOKEN_PREFIX = "sk-ant-oat01-";
const TOKEN_RUN = /^[A-Za-z0-9_-]+/;
const TOKEN_ONLY_LINE = /^[A-Za-z0-9_-]+$/;
const ESC = String.fromCharCode(27);
const BEL = String.fromCharCode(7);
const ANSI_SEQUENCE = new RegExp(
  [
    `${ESC}\\][^${BEL}${ESC}]*(?:${BEL}|${ESC}\\\\)`,
    `${ESC}\\[[0-?]*[ -/]*[@-~]`,
    `${ESC}[@-Z\\\\-_]`,
  ].join("|"),
  "g",
);

export const CLAUDE_TOKEN_EXPIRY_WARNING_DAYS = 14;

export function claudeTokenExpiryDays(
  expiresAt: string | null | undefined,
  now: Date,
): number | null {
  if (!expiresAt) return null;
  const expiry = Date.parse(expiresAt);
  if (Number.isNaN(expiry)) return null;
  return Math.max(0, Math.ceil((expiry - now.getTime()) / DAY_MS));
}

export function claudeTokenExpiryWarning(
  integration: UserClaudeIntegration | null | undefined,
  now: Date,
): string | null {
  if (integration?.status !== "connected") return null;
  const days = claudeTokenExpiryDays(integration.expires_at, now);
  if (days === null || days > CLAUDE_TOKEN_EXPIRY_WARNING_DAYS) return null;
  if (days === 0) {
    return "Your Claude token expires today. Create a new token now.";
  }
  return `Your Claude token expires in about ${days} ${days === 1 ? "day" : "days"}. Create a new token before this date.`;
}

function tokenStartingAt(
  lines: string[],
  index: number,
  start: number,
): string {
  let token = "";
  let segment = lines[index].slice(start);
  for (let next = index + 1; ; next++) {
    const run = segment.match(TOKEN_RUN)?.[0] ?? "";
    token += run;
    if (run.length < segment.length) return token;
    const following = lines[next];
    if (following === undefined || !TOKEN_ONLY_LINE.test(following)) {
      return token;
    }
    segment = following;
  }
}

export function findClaudeSetupToken(output: string): string | null {
  const lines = output
    .replace(ANSI_SEQUENCE, "")
    .split(/\r\n|\r|\n/)
    .map((line) => line.trim());
  let found: string | null = null;
  lines.forEach((line, index) => {
    let start = line.indexOf(TOKEN_PREFIX);
    while (start !== -1) {
      const token = tokenStartingAt(lines, index, start);
      if (isValidClaudeSetupToken(token)) found = token;
      start = line.indexOf(TOKEN_PREFIX, start + TOKEN_PREFIX.length);
    }
  });
  return found;
}
