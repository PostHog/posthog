const REDACTED = "[REDACTED]";
const CLAUDE_TOKEN_PREFIX = "sk-ant-oat01-";
const CLAUDE_TOKEN = /sk-ant-oat01-[A-Za-z0-9_-]+/g;
const CLAUDE_TOKEN_HEAD = /sk-ant-oat01-[A-Za-z0-9_-]*/g;
const CLAUDE_TOKEN_TAIL = /^[A-Za-z0-9_-]+/;

function isAuthorization(name: unknown): boolean {
  return typeof name === "string" && name.toLowerCase() === "authorization";
}

export function redactSecrets(value: string): string;
export function redactSecrets(value: string | undefined): string | undefined;
export function redactSecrets(value: unknown): unknown;
export function redactSecrets(value: unknown): unknown {
  if (typeof value === "string") return value.replace(CLAUDE_TOKEN, REDACTED);
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
  if (isAuthorization(record.name) && "value" in record) {
    return { ...record, value: REDACTED };
  }

  return Object.fromEntries(
    Object.entries(record).map(([key, nested]) => [
      key,
      isAuthorization(key) && typeof nested === "string"
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
  private redacting = false;
  private chunkKind: string | null = null;

  redact(event: Record<string, unknown>): Record<string, unknown>[] {
    const events: Record<string, unknown>[] = [];
    const chunk = isTextChunk(event);
    const kind = chunk ? event.notification.params.update.sessionUpdate : null;
    if (!chunk || kind !== this.chunkKind) {
      if (this.pending) events.push(this.pending);
      this.pending = null;
      this.redacting = false;
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
    if (this.redacting) {
      text = text.replace(CLAUDE_TOKEN_TAIL, "");
      if (text.length > 0) this.redacting = false;
    }
    text = text.replace(
      CLAUDE_TOKEN_HEAD,
      (match, offset: number, source: string) => {
        this.redacting = offset + match.length === source.length;
        return REDACTED;
      },
    );
    const redacted = redactSecrets(withText(event, text)) as TextEvent;
    if (!this.redacting) {
      for (let length = CLAUDE_TOKEN_PREFIX.length - 1; length > 0; length--) {
        if (text.endsWith(CLAUDE_TOKEN_PREFIX.slice(0, length))) {
          if (previous) {
            events.push(withText(previous, text.slice(0, -length)));
            this.pending = withText(redacted, text.slice(-length));
          } else {
            this.pending = redacted;
          }
          return events;
        }
      }
    }
    events.push(redacted);
    return events;
  }
}
