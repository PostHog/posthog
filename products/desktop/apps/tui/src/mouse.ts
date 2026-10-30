import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";

export interface Click {
  column: number;
  row: number;
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
// Reports presses and releases, in SGR form so columns past 223 still parse.
const ENABLE = "\x1b[?1000h\x1b[?1006h";
const DISABLE = "\x1b[?1000l\x1b[?1006l";

export function extractMouse(text: string): { keys: string; clicks: Click[] } {
  const clicks: Click[] = [];
  const keys = text.replace(MOUSE_REPORT, (_, button, column, row, kind) => {
    if (kind === "M" && Number(button) === LEFT_BUTTON) {
      clicks.push({ column: Number(column), row: Number(row) });
    }
    return "";
  });
  return { keys, clicks };
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

// Sits between the terminal and Ink, so mouse reports never reach Ink as keystrokes.
export class MouseInput {
  readonly clicks = new EventEmitter<{ click: [Click] }>();
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
      const { keys, clicks } = extractMouse(data.toString("utf8"));
      for (const click of clicks) this.clicks.emit("click", click);
      if (keys) stream.write(keys);
    };
    source.on("data", this.onData);
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
