import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";

export interface Click {
  column: number;
  row: number;
}

export interface Wheel extends Click {
  // -1 scrolls towards older lines, 1 towards newer.
  delta: -1 | 1;
}

// Screen cells, 1-based and inclusive.
export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

// SGR mouse report: ESC [ < button ; column ; row, then M on press and m on release.
const MOUSE_REPORT = new RegExp(
  `${"\u001b"}\\[<(\\d+);(\\d+);(\\d+)([Mm])`,
  "g",
);
const LEFT_BUTTON = 0;
const WHEEL_UP = 64;
const WHEEL_DOWN = 65;
// Reports presses and releases, in SGR form so columns past 223 still parse.
// Plus bracketed paste, so a pasted block reaches a composer as one paste.
const ENABLE = "\x1b[?1000h\x1b[?1006h\x1b[?2004h";
const DISABLE = "\x1b[?1000l\x1b[?1006l\x1b[?2004l";

export function extractMouse(text: string): {
  keys: string;
  clicks: Click[];
  wheels: Wheel[];
} {
  const clicks: Click[] = [];
  const wheels: Wheel[] = [];
  const keys = text.replace(MOUSE_REPORT, (_, button, column, row, kind) => {
    const at = { column: Number(column), row: Number(row) };
    if (kind !== "M") return "";
    if (Number(button) === LEFT_BUTTON) clicks.push(at);
    else if (Number(button) === WHEEL_UP) wheels.push({ ...at, delta: -1 });
    else if (Number(button) === WHEEL_DOWN) wheels.push({ ...at, delta: 1 });
    return "";
  });
  return { keys, clicks, wheels };
}

export function hitTest<T>(
  click: Click,
  boxes: Iterable<[T, Box]>,
): [T, Box] | null {
  for (const [id, box] of boxes) {
    if (
      click.column >= box.left &&
      click.column <= box.right &&
      click.row >= box.top &&
      click.row <= box.bottom
    ) {
      return [id, box];
    }
  }
  return null;
}

export type MouseEvents = EventEmitter<{
  click: [Click];
  wheel: [Wheel];
  keys: [string];
}>;

// Sits between the terminal and Ink, so mouse reports never reach Ink as keystrokes.
export class MouseInput {
  readonly events: MouseEvents = new EventEmitter();
  readonly stdin: NodeJS.ReadStream;
  private readonly onData: (data: Buffer) => void;

  constructor(
    private readonly source: NodeJS.ReadStream = process.stdin,
    private readonly stdout: NodeJS.WriteStream = process.stdout,
  ) {
    const stream = new PassThrough() as unknown as NodeJS.ReadStream;
    stream.isTTY = true;
    stream.setRawMode = (mode: boolean) => {
      source.setRawMode(mode);
      return stream;
    };
    stream.ref = () => {
      source.ref();
      return stream;
    };
    stream.unref = () => {
      source.unref();
      return stream;
    };
    this.onData = (data) => {
      const { keys, clicks, wheels } = extractMouse(data.toString("utf8"));
      for (const click of clicks) this.events.emit("click", click);
      for (const wheel of wheels) this.events.emit("wheel", wheel);
      if (keys) {
        this.events.emit("keys", keys);
        stream.write(keys);
      }
    };
    source.on("data", this.onData);
    // A listener alone does not restart a stream that was paused explicitly, such as after the theme query.
    source.resume();
    this.stdin = stream;
  }

  enable(): void {
    this.stdout.write(ENABLE);
  }

  dispose(): void {
    this.source.off("data", this.onData);
    this.stdout.write(DISABLE);
  }
}
