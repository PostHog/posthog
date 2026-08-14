import { CANVAS_PLATFORM_MANIFEST } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { FREEFORM_WHITELIST } from "./freeformWhitelist";

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
