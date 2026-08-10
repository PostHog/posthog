/**
 * CoreGraphics window-list binding — the only file in the app that touches
 * koffi.
 *
 * `CGWindowListCopyWindowInfo` returns a CFArray of CFDictionaries. Rather than
 * hand-marshalling CoreFoundation types (a dozen accessors plus a type-dispatch
 * table plus manual retain/release), we lean on the fact that its result is a
 * valid property list: serialise the whole thing to a binary plist in one call
 * and parse the bytes in JS. Six bound functions instead of a dozen.
 *
 * Reading owner name, layer, and bounds needs no macOS permission — only window
 * *titles* require Screen Recording — so this triggers no TCC prompt.
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

/** The plist shape of one window entry; every field is optional in practice. */
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
    // kCGWindowOwnerName is documented as optional, and is genuinely absent for
    // some system-owned surfaces.
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

/**
 * Turn the serialised window-list plist into our own window type. Split out from
 * the FFI so the mapping — the only part of this file that isn't a foreign call —
 * can be tested off macOS.
 */
export function parseWindowListPlist(bytes: Buffer): CgWindow[] {
  const [root] = parseBuffer(bytes);
  return Array.isArray(root) ? (root as RawWindow[]).map(toCgWindow) : [];
}

/**
 * Bind the CoreGraphics/CoreFoundation calls we need. Throws if koffi can't
 * load — callers degrade rather than propagate.
 */
function bind() {
  // Required lazily: importing koffi dlopens a native module, which we only
  // want to pay for on macOS and only once something actually polls.
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
 * Build a sampler over the live window list. Returns null off macOS, and throws
 * when the binding cannot be set up — a missing koffi prebuild and a refused
 * dlopen look identical from the outside, so the caller logs the reason rather
 * than losing it.
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
