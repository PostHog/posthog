// CGWindowListCopyWindowInfo output is also a valid property list, so
// round-tripping through a binary plist avoids hand-marshalling CoreFoundation
// types. Owner name, layer and bounds need no Screen Recording permission;
// only window titles do, so this triggers no prompt.

import { parseBuffer } from "bplist-parser";
import type { CgWindow, WindowListSampler } from "./window-list";

const kCGWindowListOptionOnScreenOnly = 1;
const kCGNullWindowID = 0;
const kCFPropertyListBinaryFormat_v1_0 = 200;

const CORE_GRAPHICS =
  "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics";
const CORE_FOUNDATION =
  "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation";

interface RawWindow {
  kCGWindowOwnerName?: unknown;
  kCGWindowLayer?: unknown;
  kCGWindowBounds?: {
    X?: unknown;
    Y?: unknown;
    Width?: unknown;
    Height?: unknown;
  };
}

const num = (value: unknown): number =>
  typeof value === "number" ? value : Number(value ?? 0) || 0;

function toCgWindow(raw: RawWindow): CgWindow {
  const bounds = raw.kCGWindowBounds ?? {};
  return {
    ownerName:
      typeof raw.kCGWindowOwnerName === "string" ? raw.kCGWindowOwnerName : "",
    layer: num(raw.kCGWindowLayer),
    bounds: {
      x: num(bounds.X),
      y: num(bounds.Y),
      width: num(bounds.Width),
      height: num(bounds.Height),
    },
  };
}

export function parseWindowListPlist(bytes: Buffer): CgWindow[] {
  const [root] = parseBuffer(bytes);
  return Array.isArray(root) ? (root as RawWindow[]).map(toCgWindow) : [];
}

export interface WindowListBindings {
  copyWindowInfo(option: number, relativeToWindow: number): unknown;
  createData(
    allocator: null,
    plist: unknown,
    format: number,
    options: number,
    error: null,
  ): unknown;
  getBytePtr(data: unknown): unknown;
  getLength(data: unknown): number | bigint;
  release(ref: unknown): void;
  decodeBytes(ptr: unknown, length: number): Uint8Array;
}

function bind(): WindowListBindings {
  // Required lazily so the native module only loads once something samples.
  const koffi = require("koffi") as typeof import("koffi");

  const cg = koffi.load(CORE_GRAPHICS);
  const cf = koffi.load(CORE_FOUNDATION);

  return {
    copyWindowInfo: cg.func(
      "void *CGWindowListCopyWindowInfo(uint32_t option, uint32_t relativeToWindow)",
    ),
    createData: cf.func(
      "void *CFPropertyListCreateData(void *allocator, void *plist, long format, unsigned long options, void **error)",
    ),
    getBytePtr: cf.func("void *CFDataGetBytePtr(void *data)"),
    getLength: cf.func("long CFDataGetLength(void *data)"),
    release: cf.func("void CFRelease(void *ref)"),
    decodeBytes: (ptr, length) =>
      koffi.decode(ptr, koffi.array("uint8", length, "Typed")) as Uint8Array,
  };
}

// Takes the bound functions as data so the CFRelease bookkeeping is testable
// off macOS.
export function createSamplerFromBindings(
  cg: WindowListBindings,
): WindowListSampler {
  return {
    sample(): CgWindow[] {
      const list = cg.copyWindowInfo(
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
      );
      if (!list) return [];

      let data: unknown = null;
      try {
        data = cg.createData(
          null,
          list,
          kCFPropertyListBinaryFormat_v1_0,
          0,
          null,
        );
        if (!data) return [];

        const length = Number(cg.getLength(data));
        if (length <= 0) return [];

        const bytes = cg.decodeBytes(cg.getBytePtr(data), length);
        return parseWindowListPlist(Buffer.from(bytes));
      } finally {
        // Both came from Copy/Create calls, so we own them.
        if (data) cg.release(data);
        cg.release(list);
      }
    },
  };
}

// Returns null off macOS; throws when the binding cannot be set up so the
// caller can log the reason.
export function createWindowListSampler(): WindowListSampler | null {
  if (process.platform !== "darwin") return null;
  return createSamplerFromBindings(bind());
}
