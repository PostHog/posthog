export interface SseEvent {
  event?: string;
  id?: string;
  data: unknown;
}

export class SseEventParser {
  private buffer = "";
  private frameBytes = 0;
  private readonly encoder = new TextEncoder();
  private currentEventName: string | null = null;
  private currentEventId: string | null = null;
  private currentData: string[] = [];

  constructor(
    private readonly onWarn?: (
      message: string,
      data?: Record<string, unknown>,
    ) => void,
    private readonly maxFrameBytes = Infinity,
  ) {}

  parse(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() || "";

    const events: SseEvent[] = [];

    for (const rawLine of lines) {
      this.frameBytes += this.encoder.encode(rawLine).byteLength + 1;
      this.checkFrameSize(this.frameBytes);
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;

      if (line === "") {
        this.frameBytes = 0;
        const event = this.flushEvent();
        if (event) {
          events.push(event);
        }
        continue;
      }

      if (line.startsWith(":")) {
        continue;
      }

      if (line.startsWith("event:")) {
        this.currentEventName = line.slice(6).trim() || null;
        continue;
      }

      if (line.startsWith("id:")) {
        this.currentEventId = line.slice(3).trim() || null;
        continue;
      }

      if (line.startsWith("data:")) {
        this.currentData.push(line.slice(5).trimStart());
      }
    }

    this.checkFrameSize(
      this.frameBytes + this.encoder.encode(this.buffer).byteLength,
    );
    return events;
  }

  private checkFrameSize(bytes: number): void {
    if (bytes <= this.maxFrameBytes) return;
    this.reset();
    throw new Error("SSE frame is too large");
  }

  reset(): void {
    this.frameBytes = 0;
    this.buffer = "";
    this.currentEventName = null;
    this.currentEventId = null;
    this.currentData = [];
  }

  private flushEvent(): SseEvent | null {
    if (this.currentData.length === 0) {
      this.currentEventName = null;
      this.currentEventId = null;
      return null;
    }

    const rawData = this.currentData.join("\n");
    this.currentData = [];

    try {
      const data = JSON.parse(rawData);
      return {
        event: this.currentEventName ?? undefined,
        id: this.currentEventId ?? undefined,
        data,
      };
    } catch {
      this.onWarn?.("SSE event JSON parse failure", { rawData });
      return null;
    } finally {
      this.currentEventName = null;
      this.currentEventId = null;
    }
  }
}
