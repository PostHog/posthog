import { CANVAS_PLATFORM_DEPENDENCIES } from "@posthog/shared";
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
      Object.entries(CANVAS_PLATFORM_DEPENDENCIES).map(([name, admission]) => [
        name,
        admission.version,
      ]),
    );
    expect(whitelist).toEqual(registry);
  });

  it("covers every whitelisted subpath specifier with a runtime import", () => {
    for (const entry of FREEFORM_WHITELIST.filter((e) =>
      isSubpathSpecifier(e.name),
    )) {
      const segments = entry.name.split("/");
      const packageName = entry.name.startsWith("@")
        ? segments.slice(0, 2).join("/")
        : segments[0];
      const admission = CANVAS_PLATFORM_DEPENDENCIES[packageName];
      expect(admission?.runtimeImports?.[entry.name], entry.name).toBeTruthy();
    }
  });
});
