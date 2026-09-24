import {
  LOOPBACK_PROXY_TOKEN,
  SECRET_HEADERS,
  TOKEN_RULES,
  type TokenRule,
} from "./secret-rules";

const REDACTED = "[REDACTED]";

interface CompiledRule {
  head: RegExp;
  tail: RegExp;
}

function escapeLiteral(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Not after a letter or digit, unless it ends an escape such as "\n" or "%20".
const WORD_START = String.raw`(?<!(?<!\\|%[0-9A-Fa-f]?)[A-Za-z0-9])`;

function tokenSource(rule: TokenRule, repeat: "+" | "*"): string {
  const start = rule.wordStart ? WORD_START : "";
  return `${start}${escapeLiteral(rule.prefix)}${rule.body.source}${repeat}`;
}

const RULES: CompiledRule[] = TOKEN_RULES.map((rule) => ({
  head: new RegExp(tokenSource(rule, "*"), "g"),
  tail: new RegExp(`^${rule.body.source}*`),
}));

// A JWT body contains dots, so a match can end in sentence punctuation. The dots belong to
// the token only when more of it follows; at the end of a chunk that is not yet known.
const TRAILING_DOTS = /\.+$/;

function trailingDots(match: string): string {
  return TRAILING_DOTS.exec(match)?.[0] ?? "";
}

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

const LOOPBACK_TAIL: CompiledRule = {
  head: LOOPBACK_PROXY_TOKEN,
  tail: /^[A-Za-z0-9_-]*/,
};
const LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "[::1]"];
const LOOPBACK_AFTER_HOST = /^:(?:\d{0,5}|\d{1,5}\/[A-Za-z0-9_-]{0,31})$/;
const LOOPBACK_HOLD_MAX = 2 + 9 + 6 + 1 + 31;

/** Whether `text` could still grow into a loopback URL with a full path token. */
function isLoopbackPrefix(text: string): boolean {
  if (text.length <= 2) return "//".startsWith(text);
  if (!text.startsWith("//")) return false;
  const rest = text.slice(2);
  return LOOPBACK_HOSTS.some(
    (host) =>
      host.startsWith(rest) ||
      (rest.startsWith(host) &&
        LOOPBACK_AFTER_HOST.test(rest.slice(host.length))),
  );
}

function loopbackPrefixLength(text: string): number {
  const from = Math.max(0, text.length - LOOPBACK_HOLD_MAX);
  for (let start = from; start < text.length; start++) {
    if (text[start] === "/" && isLoopbackPrefix(text.slice(start))) {
      return text.length - start;
    }
  }
  return 0;
}

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
  if (typeof value === "string") {
    return value
      .replace(TOKEN, (match) => REDACTED + trailingDots(match))
      .replace(LOOPBACK_PROXY_TOKEN, `$1${REDACTED}`);
  }
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

/**
 * `JSON.stringify` replacer that masks secret headers without a recursive
 * walk, so cycles fail fast. Run `redactSecrets` over the output for tokens.
 */
export function secretHeaderReplacer(key: string, value: unknown): unknown {
  if (isSecretHeader(key) && typeof value === "string") return REDACTED;
  if (value instanceof Error) {
    return { name: value.name, message: value.message, stack: value.stack };
  }
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    if (isSecretHeader(record.name) && "value" in record) {
      return { ...record, value: REDACTED };
    }
  }
  return value;
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
  private heldDots = 0;

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
    const previousText =
      previous?.notification.params.update.content.text ?? "";
    let text = previousText + event.notification.params.update.content.text;
    this.pending = null;
    let heldDots = 0;
    if (this.active) {
      // The held dots of the previous chunk are part of the continuation.
      const start = previousText.length - this.heldDots;
      const rest = text.slice(start);
      const match = this.active.tail.exec(rest)?.[0] ?? "";
      const dots = trailingDots(match);
      const remainder = rest.slice(match.length - dots.length);
      text = text.slice(0, start) + remainder;
      if (remainder === dots) heldDots = dots.length;
      else if (remainder.length > 0) this.active = null;
    }
    for (const rule of RULES) {
      text = text.replace(
        rule.head,
        (match, offset: number, source: string) => {
          const dots = trailingDots(match);
          if (offset + match.length === source.length) {
            this.active = rule;
            heldDots = dots.length;
          }
          return REDACTED + dots;
        },
      );
    }
    text = text.replace(
      LOOPBACK_PROXY_TOKEN,
      (match, host: string, offset: number, source: string) => {
        if (offset + match.length === source.length) {
          this.active = LOOPBACK_TAIL;
          heldDots = 0;
        }
        return host + REDACTED;
      },
    );
    const redacted = redactSecrets(withText(event, text)) as TextEvent;
    const held = this.active
      ? heldDots
      : Math.max(partialPrefixLength(text), loopbackPrefixLength(text));
    this.heldDots = this.active ? heldDots : 0;
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
