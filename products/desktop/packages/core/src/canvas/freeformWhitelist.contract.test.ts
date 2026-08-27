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

  // CANVAS_PLATFORM_MANIFEST is a hand-vendored copy of the builder's
  // manifest.json, so it can silently fall behind. Drift in the fields below
  // ships, because the client reads them: admit an import specifier or bump the
  // SDK version server-side without copying it here, and a canvas previews
  // against one contract but publishes against another. `csp` and `limits` are
  // vendored but unread, and are deliberately left out of this comparison.
  it("matches the builder's manifest on the fields the client reads", async () => {
    const { readFile } = await import("node:fs/promises");
    const manifest = JSON.parse(
      await readFile(
        new URL(
          "../../../../../canvas/packages/canvas_builder/manifest.json",
          import.meta.url,
        ).pathname,
        "utf8",
      ),
    );

    expect(CANVAS_PLATFORM_MANIFEST.canvasSdkVersion).toEqual(
      manifest.canvasSdkVersion,
    );
    expect(CANVAS_PLATFORM_MANIFEST.supportedSdkVersions).toEqual(
      manifest.supportedSdkVersions,
    );
    expect(CANVAS_PLATFORM_MANIFEST.allowedImportSpecifiers).toEqual(
      manifest.allowedImportSpecifiers,
    );
    expect(CANVAS_PLATFORM_MANIFEST.dependencies).toEqual(
      manifest.dependencies,
    );
    expect(CANVAS_PLATFORM_MANIFEST.runtimeImports).toEqual(
      manifest.runtimeImports,
    );
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
