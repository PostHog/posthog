import { SECRET_HEADERS, TOKEN_RULES, type TokenRule } from "./secret-rules";

const REDACTED = "[REDACTED]";

interface CompiledRule {
  head: RegExp;
  tail: RegExp;
}

function escapeLiteral(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function tokenSource(rule: TokenRule, repeat: "+" | "*"): string {
  return `${escapeLiteral(rule.prefix)}${rule.body.source}${repeat}`;
}

const RULES: CompiledRule[] = TOKEN_RULES.map((rule) => ({
  head: new RegExp(tokenSource(rule, "*"), "g"),
  tail: new RegExp(`^${rule.body.source}+`),
}));

const TOKEN = new RegExp(
  TOKEN_RULES.map((rule) => tokenSource(rule, "+")).join("|"),
  "g",
);

const PARTIAL_PREFIXES = [
  ...new Set(
    TOKEN_RULES.flatMap((rule) =>
      Array.from({ length: rule.prefix.length - 1 }, (_, index) =>
        rule.prefix.slice(0, index + 1),
      ),
    ),
  ),
].sort((left, right) => right.length - left.length);

const SECRET_HEADER_NAMES = new Set(SECRET_HEADERS);

function isSecretHeader(name: unknown): boolean {
  return (
    typeof name === "string" && SECRET_HEADER_NAMES.has(name.toLowerCase())
  );
}

function partialPrefixLength(text: string): number {
  for (const prefix of PARTIAL_PREFIXES) {
    if (text.endsWith(prefix)) return prefix.length;
  }
  return 0;
}

export function redactSecrets(value: string): string;
export function redactSecrets(value: string | undefined): string | undefined;
export function redactSecrets(value: unknown): unknown;
export function redactSecrets(value: unknown): unknown {
  if (typeof value === "string") return value.replace(TOKEN, REDACTED);
  if (Array.isArray(value)) return value.map(redactSecrets);
  if (value instanceof Error)
    return {
      name: value.name,
      message: redactSecrets(value.message),
      stack: redactSecrets(value.stack),
    };
  if (value instanceof Date) return value;
  if (value === null || typeof value !== "object") return value;

  const record = value as Record<string, unknown>;
  if (isSecretHeader(record.name) && "value" in record) {
    return { ...record, value: REDACTED };
  }

  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [
      key,
      isSecretHeader(key) && typeof nested === "string"
        ? REDACTED
        : redactSecrets(nested),
    ]),
  );
}

type TextEvent = Record<string, unknown> & {
  notification: {
    method: "session/update";
    params: {
      update: {
        sessionUpdate: string;
        content: { type: "text"; text: string };
      };
    };
  };
};

function isTextChunk(event: Record<string, unknown>): event is TextEvent {
  const notification = event.notification as
    | TextEvent["notification"]
    | undefined;
  const update = notification?.params?.update;
  return (
    notification?.method === "session/update" &&
    (update?.sessionUpdate === "agent_message_chunk" ||
      update?.sessionUpdate === "agent_thought_chunk") &&
    update.content?.type === "text" &&
    typeof update.content.text === "string"
  );
}

function withText(event: TextEvent, text: string): TextEvent {
  return {
    ...event,
    notification: {
      ...event.notification,
      params: {
        ...event.notification.params,
        update: {
          ...event.notification.params.update,
          content: { ...event.notification.params.update.content, text },
        },
      },
    },
  };
}

export class SecretEventRedactor {
  private pending: TextEvent | null = null;
  private active: CompiledRule | null = null;
  private chunkKind: string | null = null;

  redact(event: Record<string, unknown>): Record<string, unknown>[] {
    const events: Record<string, unknown>[] = [];
    const chunk = isTextChunk(event);
    const kind = chunk ? event.notification.params.update.sessionUpdate : null;
    if (!chunk || kind !== this.chunkKind) {
      if (this.pending) events.push(this.pending);
      this.pending = null;
      this.active = null;
    }
    this.chunkKind = kind;
    if (!chunk) {
      events.push(redactSecrets(event) as Record<string, unknown>);
      return events;
    }
    const previous = this.pending;
    let text =
      (previous?.notification.params.update.content.text ?? "") +
      event.notification.params.update.content.text;
    this.pending = null;
    if (this.active) {
      text = text.replace(this.active.tail, "");
      if (text.length > 0) this.active = null;
    }
    for (const rule of RULES) {
      text = text.replace(
        rule.head,
        (match, offset: number, source: string) => {
          if (offset + match.length === source.length) this.active = rule;
          return REDACTED;
        },
      );
    }
    const redacted = redactSecrets(withText(event, text)) as TextEvent;
    const held = this.active ? 0 : partialPrefixLength(text);
    if (held > 0) {
      if (previous) {
        events.push(withText(previous, text.slice(0, -held)));
        this.pending = withText(redacted, text.slice(-held));
      } else {
        this.pending = redacted;
      }
      return events;
    }
    events.push(redacted);
    return events;
  }
}
