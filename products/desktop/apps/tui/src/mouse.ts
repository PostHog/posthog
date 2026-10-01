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
// Set on a report the pointer's motion sent rather than a button.
const MOTION = 32;
// The button bits of a motion report when no button is held.
const NO_BUTTON = 3;
// Reports presses, releases and pointer motion, in SGR form so columns past 223 still parse.
// Plus bracketed paste, so a pasted block reaches a composer as one paste.
const ENABLE = "\x1b[?1003h\x1b[?1006h\x1b[?2004h";
const DISABLE = "\x1b[?1003l\x1b[?1006l\x1b[?2004l";

export interface MouseReports {
  keys: string;
  // Left button only: pressed, moved while held, and let go.
  presses: Click[];
  drags: Click[];
  releases: Click[];
  wheels: Wheel[];
  // The pointer moving with no button held.
  moves: Click[];
}

export function extractMouse(text: string): MouseReports {
  const reports: Omit<MouseReports, "keys"> = {
    presses: [],
    drags: [],
    releases: [],
    wheels: [],
    moves: [],
  };
  const keys = text.replace(MOUSE_REPORT, (_, code, column, row, kind) => {
    const at = { column: Number(column), row: Number(row) };
    const button = Number(code);
    if (kind === "m") {
      if (button === LEFT_BUTTON) reports.releases.push(at);
    } else if (button & MOTION) {
      const held = button & ~MOTION;
      if (held === NO_BUTTON) reports.moves.push(at);
      else if (held === LEFT_BUTTON) reports.drags.push(at);
    } else if (button === LEFT_BUTTON) reports.presses.push(at);
    else if (button === WHEEL_UP) reports.wheels.push({ ...at, delta: -1 });
    else if (button === WHEEL_DOWN) reports.wheels.push({ ...at, delta: 1 });
    return "";
  });
  return { keys, ...reports };
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
  press: [Click];
  drag: [Click];
  release: [Click];
  wheel: [Wheel];
  move: [Click];
  keys: [string];
}>;

// Sits between the terminal and Ink, so mouse reports never reach Ink as keystrokes.
export class MouseInput {
  readonly events: MouseEvents = new EventEmitter();
  readonly stdin: NodeJS.ReadStream;
  private readonly onData: (data: Buffer) => void;
  private disposed = false;

  constructor(
    private readonly source: NodeJS.ReadStream = process.stdin,
    private readonly stdout: NodeJS.WriteStream = process.stdout,
  ) {
    const stream = new PassThrough() as unknown as NodeJS.ReadStream;
    stream.isTTY = true;
    // After dispose, a reloaded copy owns the terminal; this copy's Ink teardown must not turn raw mode off under it.
    stream.setRawMode = (mode: boolean) => {
      if (!this.disposed) source.setRawMode(mode);
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
      const { keys, presses, drags, releases, wheels, moves } = extractMouse(
        data.toString("utf8"),
      );
      for (const at of presses) this.events.emit("press", at);
      for (const at of drags) this.events.emit("drag", at);
      for (const at of releases) this.events.emit("release", at);
      for (const move of moves) this.events.emit("move", move);
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
    this.disposed = true;
    this.source.off("data", this.onData);
    this.stdout.write(DISABLE);
  }
}
