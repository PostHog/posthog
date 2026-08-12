export interface SseEvent {
  id?: string;
  data: unknown;
}

export class SseEventParser {
  private buffer = "";
  private currentEventId: string | null = null;
  private currentData: string | null = null;

  parse(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() || "";

    const events: SseEvent[] = [];

    for (const line of lines) {
      if (line.startsWith("id: ")) {
        this.currentEventId = line.slice(4).trim();
      } else if (line.startsWith("data: ")) {
        this.currentData = line.slice(6);
      } else if (line === "" && this.currentData !== null) {
        try {
          const data = JSON.parse(this.currentData);
          events.push({
            id: this.currentEventId ?? undefined,
            data,
          });
        } catch {
          // Skip malformed data
        }
        this.currentData = null;
        this.currentEventId = null;
      }
    }

    return events;
  }

  reset(): void {
    this.buffer = "";
    this.currentEventId = null;
    this.currentData = null;
  }
}
