import { PassThrough } from "node:stream";
import { type Instance, render } from "ink";
import type { ReactElement } from "react";

// Renders into a real Ink instance on fake terminal streams, so tests can type raw bytes at it.
export function renderInTerminal(element: ReactElement): {
  instance: Instance;
  type: (bytes: string) => void;
} {
  const stdin = Object.assign(new PassThrough(), {
    isTTY: true,
    setRawMode: () => stdin,
    ref: () => stdin,
    unref: () => stdin,
  });
  const stdout = Object.assign(new PassThrough(), {
    isTTY: true,
    columns: 100,
    rows: 30,
  });
  stdout.resume();
  const instance = render(element, {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    exitOnCtrlC: false,
    patchConsole: false,
    kittyKeyboard: { mode: "enabled" },
  });
  return { instance, type: (bytes) => stdin.write(bytes) };
}
