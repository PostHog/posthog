import { StdinBuffer } from "@earendil-works/pi-tui";
import { useEffect, useRef } from "react";
import type { Click, MouseEvents, Wheel } from "../mouse";

export interface TerminalHandlers {
  onPress: (at: Click) => void;
  onDrag: (at: Click) => void;
  onRelease: (at: Click) => void;
  onMove: (at: Click) => void;
  onWheel: (at: Wheel) => void;
  // One key sequence or a bracketed paste, split from the raw input.
  onKey: (sequence: string) => void;
}

// Subscribes once to the mouse and key stream; the latest handlers run, so they can read current state.
export function useTerminalInput(
  mouse: MouseEvents | undefined,
  handlers: TerminalHandlers,
): void {
  const latest = useRef(handlers);
  latest.current = handlers;
  useEffect(() => {
    if (!mouse) return;
    const press = (at: Click): void => latest.current.onPress(at);
    const drag = (at: Click): void => latest.current.onDrag(at);
    const release = (at: Click): void => latest.current.onRelease(at);
    const wheel = (at: Wheel): void => latest.current.onWheel(at);
    const move = (at: Click): void => latest.current.onMove(at);
    const keys = new StdinBuffer();
    keys.on("data", (sequence) => latest.current.onKey(sequence));
    keys.on("paste", (text) =>
      latest.current.onKey(`\x1b[200~${text}\x1b[201~`),
    );
    const raw = (data: string): void => keys.process(data);
    mouse.on("press", press);
    mouse.on("drag", drag);
    mouse.on("release", release);
    mouse.on("wheel", wheel);
    mouse.on("move", move);
    mouse.on("keys", raw);
    return () => {
      mouse.off("press", press);
      mouse.off("drag", drag);
      mouse.off("release", release);
      mouse.off("wheel", wheel);
      mouse.off("move", move);
      mouse.off("keys", raw);
      keys.destroy();
    };
  }, [mouse]);
}
