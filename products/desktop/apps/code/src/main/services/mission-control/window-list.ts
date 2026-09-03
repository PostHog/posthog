export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CgWindow {
  ownerName: string;
  /** Cocoa window level; normal app windows are 0. */
  layer: number;
  bounds: Rect;
}

export interface WindowListSampler {
  sample(): CgWindow[];
}
