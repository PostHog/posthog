import {
  CANVAS_PLATFORM_MANIFEST,
  CANVAS_SDK_SPECIFIER,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { checkFreeformImports, FREEFORM_WHITELIST } from "./freeformWhitelist";

function isSubpathSpecifier(name: string): boolean {
  const segments = name.split("/");
  return name.startsWith("@") ? segments.length > 2 : segments.length > 1;
}

describe("freeform whitelist ↔ platform dependency registry", () => {
  // The legacy runtime's import whitelist and the build pipeline's platform
  // dependency registry describe the same pinned package set. If one moves
  // without the other, a canvas that previews in one tier fails in the other.
  it("pins the same packages at the same versions", () => {
    const whitelist = Object.fromEntries(
      FREEFORM_WHITELIST.filter((entry) => !isSubpathSpecifier(entry.name)).map(
        (entry) => [entry.name, entry.version],
      ),
    );
    const registry = Object.fromEntries(
      Object.entries(CANVAS_PLATFORM_MANIFEST.dependencies).map(
        ([name, admission]) => [name, admission.version],
      ),
    );
    expect(whitelist).toEqual(registry);
  });

  // The canvas SDK has no import-map entry (the sandbox and builder inline it),
  // so it must be admitted by BOTH the client import check and the vendored
  // platform contract — one without the other means a canvas that previews
  // fails to publish, or the reverse.
  it("admits the canvas SDK specifier on both sides", () => {
    expect(CANVAS_PLATFORM_MANIFEST.allowedImportSpecifiers).toContain(
      CANVAS_SDK_SPECIFIER,
    );
    expect(
      checkFreeformImports(`import { ph } from "${CANVAS_SDK_SPECIFIER}";`).ok,
    ).toBe(true);
  });

  it("covers every whitelisted subpath specifier with a runtime import", () => {
    for (const entry of FREEFORM_WHITELIST.filter((e) =>
      isSubpathSpecifier(e.name),
    )) {
      const runtimeImports: Record<string, string> =
        CANVAS_PLATFORM_MANIFEST.runtimeImports;
      expect(runtimeImports[entry.name], entry.name).toBeTruthy();
    }
  });
});
