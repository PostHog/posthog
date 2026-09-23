import {
  CANVAS_PLATFORM_MANIFEST,
  CANVAS_SDK_MODULE_SOURCE,
  CANVAS_SDK_SPECIFIER,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { buildImportMap, FREEFORM_WHITELIST } from "./freeformWhitelist";

function isSubpathSpecifier(name: string): boolean {
  const segments = name.split("/");
  return name.startsWith("@") ? segments.length > 2 : segments.length > 1;
}

// Comments and blank lines carry no module semantics, and the vendored copy
// drops the original's header, so compare only the code.
function codeLines(source: string): string[] {
  return source
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "" && !line.startsWith("//"));
}

function builderFile(relativePath: string): Promise<string> {
  return import("node:fs/promises").then(({ readFile }) =>
    readFile(
      new URL(
        `../../../../../canvas/packages/canvas_builder/${relativePath}`,
        import.meta.url,
      ).pathname,
      "utf8",
    ),
  );
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
    const manifest = JSON.parse(await builderFile("manifest.json"));

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

  // Admission and resolution used to be one list. Now the preview admits what
  // the manifest admits but still resolves through FREEFORM_WHITELIST, so a
  // specifier added server-side passes the import check and then dies in the
  // iframe on "Failed to resolve module specifier". The SDK is the one
  // exception: the document mints it as a blob at load time.
  it("resolves every admitted import specifier in the preview import map", () => {
    const { imports } = buildImportMap();

    for (const specifier of CANVAS_PLATFORM_MANIFEST.allowedImportSpecifiers) {
      if (specifier === CANVAS_SDK_SPECIFIER) continue;
      expect(imports[specifier], specifier).toBeTruthy();
    }
  });

  // The preview serves its own copy of the SDK module, so a change to the
  // builder's copy alone ships an author an export that resolves in one tier
  // and is undefined in the other.
  it("vendors the builder's canvas SDK module verbatim", async () => {
    expect(codeLines(CANVAS_SDK_MODULE_SOURCE)).toEqual(
      codeLines(await builderFile("canvas-sdk.mjs")),
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
