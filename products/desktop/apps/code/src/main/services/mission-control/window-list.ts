export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One on-screen window, as reported by CoreGraphics. */
export interface CgWindow {
  /** Empty for some system-owned surfaces, which CoreGraphics leaves unnamed. */
  ownerName: string;
  /** Cocoa window level. Normal app windows are 0. */
  layer: number;
  bounds: Rect;
}

/** Reads the current on-screen window list. Faked in tests. */
export interface WindowListSampler {
  sample(): CgWindow[];
}
