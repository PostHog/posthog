/**
 * CoreGraphics window-list binding — the only file that touches koffi.
 *
 * `CGWindowListCopyWindowInfo` returns a CFArray of CFDictionaries, which is also
 * a valid property list. Serialising that to a binary plist and parsing the bytes
 * in JS takes five bound functions; hand-marshalling the CoreFoundation types
 * would take a dozen plus manual retain and release.
 *
 * Owner name, layer and bounds need no permission. Only window *titles* require
 * Screen Recording, so this triggers no prompt.
 */

import { parseBuffer } from "bplist-parser";
import type { CgWindow, WindowListSampler } from "./window-list";

const kCGWindowListOptionOnScreenOnly = 1;
const kCGNullWindowID = 0;
const kCFPropertyListBinaryFormat_v1_0 = 200;

const CORE_GRAPHICS =
  "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics";
const CORE_FOUNDATION =
  "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation";

/** Every field is optional in practice, including the owner name. */
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
    // CoreGraphics capitalises these; our own type does not.
    bounds: {
      x: num(bounds.X),
      y: num(bounds.Y),
      width: num(bounds.Width),
      height: num(bounds.Height),
    },
  };
}

/** Split out from the FFI so the mapping can be tested off macOS. */
export function parseWindowListPlist(bytes: Buffer): CgWindow[] {
  const [root] = parseBuffer(bytes);
  return Array.isArray(root) ? (root as RawWindow[]).map(toCgWindow) : [];
}

function bind() {
  // Required lazily so loading a native module is paid for only on macOS, and
  // only once something actually samples.
  const koffi = require("koffi") as typeof import("koffi");

  const cg = koffi.load(CORE_GRAPHICS);
  const cf = koffi.load(CORE_FOUNDATION);

  return {
    koffi,
    copyWindowInfo: cg.func(
      "void *CGWindowListCopyWindowInfo(uint32_t option, uint32_t relativeToWindow)",
    ),
    createData: cf.func(
      "void *CFPropertyListCreateData(void *allocator, void *plist, long format, unsigned long options, void **error)",
    ),
    getBytePtr: cf.func("void *CFDataGetBytePtr(void *data)"),
    getLength: cf.func("long CFDataGetLength(void *data)"),
    release: cf.func("void CFRelease(void *ref)"),
  };
}

/**
 * Returns null off macOS, and throws when the binding cannot be set up — a missing
 * koffi prebuild and a dlopen the hardened runtime refused look identical from
 * outside, so the caller logs the reason rather than losing it.
 */
export function createWindowListSampler(): WindowListSampler | null {
  if (process.platform !== "darwin") return null;

  const cg = bind();

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

        const bytes = cg.koffi.decode(
          cg.getBytePtr(data),
          cg.koffi.array("uint8", length, "Typed"),
        ) as Uint8Array;

        return parseWindowListPlist(Buffer.from(bytes));
      } finally {
        // Both came from Copy/Create calls, so we own them.
        if (data) cg.release(data);
        cg.release(list);
      }
    },
  };
}
