import {
  SKETCHPAD_PRESENCE_INTERVAL_MS,
  SKETCHPAD_PRESENCE_MAX_SELECTED_IDS,
  type SketchpadPresenceCaret,
  type SketchpadPresenceInput,
  type SketchpadPresencePoint,
  type SketchpadViewport,
} from "@posthog/shared";

export class SketchpadPresenceSender {
  private presence: SketchpadPresenceInput;
  private lastSentAt = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private stopped = false;
  private inFlight = false;
  private dirty = false;

  constructor(
    clientId: string,
    private readonly send: (presence: SketchpadPresenceInput) => Promise<void>,
  ) {
    this.presence = {
      clientId,
      cursor: null,
      viewport: null,
      selectedIds: [],
      carets: [],
    };
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.timer);
  }

  reportCursor(world: SketchpadPresencePoint | null): void {
    const cursor =
      world === null
        ? null
        : { x: Math.round(world.x), y: Math.round(world.y) };
    const last = this.presence.cursor;
    if (last?.x === cursor?.x && last?.y === cursor?.y) return;
    this.presence.cursor = cursor;
    this.schedule();
  }

  reportSelection(ids: readonly string[]): void {
    const length = Math.min(ids.length, SKETCHPAD_PRESENCE_MAX_SELECTED_IDS);
    const last = this.presence.selectedIds;
    if (length === last.length && last.every((id, index) => id === ids[index]))
      return;
    this.presence.selectedIds = ids.slice(0, length);
    this.schedule();
  }

  reportViewport(viewport: SketchpadViewport): void {
    const last = this.presence.viewport;
    if (
      last?.x === viewport.x &&
      last.y === viewport.y &&
      last.zoom === viewport.zoom
    )
      return;
    this.presence.viewport = viewport;
    this.schedule();
  }

  reportCaret(caret: SketchpadPresenceCaret | null): void {
    const last = this.presence.carets[0];
    if (
      last?.key === caret?.key &&
      last?.anchor === caret?.anchor &&
      last?.focus === caret?.focus
    )
      return;
    this.presence.carets = caret === null ? [] : [caret];
    this.schedule();
  }

  private schedule(): void {
    if (this.stopped) return;
    this.dirty = true;
    if (this.inFlight || this.timer !== undefined) return;
    const delay =
      SKETCHPAD_PRESENCE_INTERVAL_MS - (Date.now() - this.lastSentAt);
    if (delay <= 0) {
      void this.flush();
    } else {
      this.timer = setTimeout(() => {
        this.timer = undefined;
        void this.flush();
      }, delay);
    }
  }

  private async flush(): Promise<void> {
    if (this.stopped) return;
    this.inFlight = true;
    this.dirty = false;
    this.lastSentAt = Date.now();
    try {
      await this.send({ ...this.presence });
    } catch {
    } finally {
      this.inFlight = false;
      if (this.dirty) this.schedule();
    }
  }
}
