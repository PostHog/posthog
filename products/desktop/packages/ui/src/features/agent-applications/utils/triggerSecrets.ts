import type { AgentSpec } from "@posthog/shared/agent-platform-types";

/**
 * Secrets a trigger needs in encrypted_env, derived from the spec. Mirrors the
 * agent-console `triggerSecrets.ts` (itself a mirror of the agent-shared +
 * Django `spec_schema` source). Used to surface "missing secret" warnings on
 * triggers/mcps alongside the spec's top-level `secrets[]`.
 */

export const SLACK_SIGNING_SECRET_KEY = "SLACK_SIGNING_SECRET";
export const SLACK_BOT_TOKEN_KEY = "SLACK_BOT_TOKEN";

export interface DerivedTriggerSecret {
  key: string;
  label: string;
  description: string;
  /** Which trigger type contributed this requirement. */
  trigger: string;
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}
function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

const SLACK_SECRETS: Omit<DerivedTriggerSecret, "trigger">[] = [
  {
    key: SLACK_SIGNING_SECRET_KEY,
    label: "Slack signing secret",
    description:
      "Your Slack app's signing secret (Settings → Basic Information). Verifies inbound Slack event signatures.",
  },
  {
    key: SLACK_BOT_TOKEN_KEY,
    label: "Slack bot user OAuth token",
    description:
      "Your Slack app's bot token (xoxb-…), from Settings → Install App. Used by native Slack tools.",
  },
];

/** A secret referenced by a webhook/jwt auth mode, or null. */
function authModeSecret(
  mode: unknown,
): Omit<DerivedTriggerSecret, "trigger"> | null {
  const m = rec(mode);
  if (m.type === "shared_secret" && str(m.secret_ref)) {
    return {
      key: str(m.secret_ref) as string,
      label: "Webhook shared secret",
      description: `Expected value for the \`${str(m.header) ?? ""}\` header. Callers must send this exact secret.`,
    };
  }
  if (m.type === "jwt" && str(m.issuer_secret_ref)) {
    return {
      key: str(m.issuer_secret_ref) as string,
      label: "JWT signing secret",
      description: "HMAC secret used to verify inbound JWT signatures.",
    };
  }
  return null;
}

/** Required secrets for a single trigger (slack keys + its auth-mode secrets). */
export function triggerRequiredSecretsFor(
  trigger: unknown,
): Omit<DerivedTriggerSecret, "trigger">[] {
  const type = str(rec(trigger).type) ?? "trigger";
  const out: Omit<DerivedTriggerSecret, "trigger">[] = [];
  if (type === "slack") out.push(...SLACK_SECRETS);
  const modes = rec(rec(trigger).auth).modes;
  for (const mode of Array.isArray(modes) ? modes : []) {
    const s = authModeSecret(mode);
    if (s) out.push(s);
  }
  return out;
}

/** Per-trigger required secrets, deduped by key (first trigger wins). */
export function getTriggerRequiredSecrets(
  spec: AgentSpec,
): DerivedTriggerSecret[] {
  const triggers = Array.isArray(spec.triggers) ? spec.triggers : [];
  const seen = new Set<string>();
  const out: DerivedTriggerSecret[] = [];
  const add = (
    s: Omit<DerivedTriggerSecret, "trigger">,
    trigger: string,
  ): void => {
    if (seen.has(s.key)) return;
    seen.add(s.key);
    out.push({ ...s, trigger });
  };
  for (const t of triggers) {
    const type = str(rec(t).type) ?? "trigger";
    if (type === "slack") {
      for (const s of SLACK_SECRETS) add(s, type);
    }
    for (const mode of Array.isArray(rec(rec(t).auth).modes)
      ? (rec(rec(t).auth).modes as unknown[])
      : []) {
      const s = authModeSecret(mode);
      if (s) add(s, type);
    }
  }
  return out;
}
