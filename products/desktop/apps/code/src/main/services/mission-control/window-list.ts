export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** One on-screen window, as reported by CoreGraphics. */
export interface CgWindow {
  /** Owning application's name; "Dock" for Mission Control's own surfaces. */
  ownerName: string;
  /** Cocoa window level. Normal app windows are 0. */
  layer: number;
  bounds: Rect;
}

/**
 * Reads the current on-screen window list. Implemented over CoreGraphics on
 * macOS; faked in tests. Synchronous because the underlying call is a cheap
 * in-process query and the poller wants no scheduling jitter between the sample
 * and the decision made from it.
 */
export interface WindowListSampler {
  sample(): CgWindow[];
}
