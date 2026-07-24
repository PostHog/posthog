import { describe, expect, test, vi } from "vitest";
import { enrichFileForAgent, type FileEnrichmentDeps } from "./file-enricher";

function makeDeps(overrides: {
  toInlineCommentsReturn?: string;
  callsCount?: number;
  initCallsCount?: number;
  parseRejects?: Error;
  isSupported?: boolean;
  getApiKey?: () => string | Promise<string>;
  findImportsInSource?: () => Promise<unknown[]>;
  getWrappersForFile?: () => Promise<unknown[]>;
}): {
  deps: FileEnrichmentDeps;
  parseSpy: ReturnType<typeof vi.fn>;
  enrichFromApiSpy: ReturnType<typeof vi.fn>;
  getApiKeySpy: ReturnType<typeof vi.fn>;
  findImportsSpy: ReturnType<typeof vi.fn>;
  getWrappersSpy: ReturnType<typeof vi.fn>;
} {
  const enrichFromApiSpy = vi.fn(async () => ({
    toInlineComments: () =>
      overrides.toInlineCommentsReturn ?? "enriched content",
  }));

  const parseSpy = vi.fn(async () => {
    if (overrides.parseRejects) throw overrides.parseRejects;
    return {
      calls: Array.from({ length: overrides.callsCount ?? 1 }),
      initCalls: Array.from({ length: overrides.initCallsCount ?? 0 }),
      enrichFromApi: enrichFromApiSpy,
    };
  });

  const getApiKeySpy = vi.fn(overrides.getApiKey ?? (() => "phx_test"));
  const findImportsSpy = vi.fn(
    overrides.findImportsInSource ?? (async () => []),
  );
  const getWrappersSpy = vi.fn(
    overrides.getWrappersForFile ?? (async () => []),
  );

  const deps: FileEnrichmentDeps = {
    enricher: {
      isSupported: vi.fn(() => overrides.isSupported ?? true),
      parse: parseSpy,
      findImportsInSource: findImportsSpy,
      getWrappersForFile: getWrappersSpy,
    } as unknown as FileEnrichmentDeps["enricher"],
    apiConfig: {
      apiUrl: "https://test.posthog.com",
      projectId: 1,
      getApiKey: getApiKeySpy,
    },
  };

  return {
    deps,
    parseSpy,
    enrichFromApiSpy,
    getApiKeySpy,
    findImportsSpy,
    getWrappersSpy,
  };
}

describe("enrichFileForAgent", () => {
  test("returns null for unsupported extension", async () => {
    const { deps, parseSpy } = makeDeps({});
    const result = await enrichFileForAgent(
      deps,
      "/tmp/notes.txt",
      "some text",
    );
    expect(result).toBeNull();
    expect(parseSpy).not.toHaveBeenCalled();
  });

  test("returns null for empty content", async () => {
    const { deps, parseSpy } = makeDeps({});
    const result = await enrichFileForAgent(deps, "/tmp/code.ts", "");
    expect(result).toBeNull();
    expect(parseSpy).not.toHaveBeenCalled();
  });

  test("returns null for content > 1MB", async () => {
    const { deps, parseSpy } = makeDeps({});
    const huge = "x".repeat(1_000_001);
    const result = await enrichFileForAgent(deps, "/tmp/code.ts", huge);
    expect(result).toBeNull();
    expect(parseSpy).not.toHaveBeenCalled();
  });

  test("returns null when language not supported by enricher", async () => {
    const { deps, parseSpy } = makeDeps({ isSupported: false });
    const result = await enrichFileForAgent(
      deps,
      "/tmp/code.ts",
      "posthog.capture('x');",
    );
    expect(result).toBeNull();
    expect(parseSpy).not.toHaveBeenCalled();
  });

  test("returns null when no PostHog calls detected", async () => {
    const { deps, enrichFromApiSpy } = makeDeps({
      callsCount: 0,
      initCallsCount: 0,
    });
    const result = await enrichFileForAgent(
      deps,
      "/tmp/code.ts",
      "posthog.capture('x');",
    );
    expect(result).toBeNull();
    expect(enrichFromApiSpy).not.toHaveBeenCalled();
  });

  test("returns null and skips parse when content has no posthog reference AND no relative imports", async () => {
    const { deps, parseSpy, findImportsSpy } = makeDeps({});
    const result = await enrichFileForAgent(
      deps,
      "/tmp/code.ts",
      "const x = 1;\nfunction foo() {}",
    );
    expect(result).toBeNull();
    expect(parseSpy).not.toHaveBeenCalled();
    expect(findImportsSpy).not.toHaveBeenCalled();
  });

  test("relative import with no resolvable wrapper → skips parse", async () => {
    const { deps, parseSpy, findImportsSpy, getWrappersSpy } = makeDeps({
      findImportsInSource: async () => [
        {
          localName: "foo",
          importedName: "foo",
          resolvedAbsPath: "/tmp/foo.ts",
        },
      ],
      getWrappersForFile: async () => [],
    });
    const result = await enrichFileForAgent(
      deps,
      "/tmp/app.ts",
      'import { foo } from "./foo";\nfoo("x");',
    );
    expect(result).toBeNull();
    expect(findImportsSpy).toHaveBeenCalled();
    expect(getWrappersSpy).toHaveBeenCalledWith("/tmp/foo.ts");
    expect(parseSpy).not.toHaveBeenCalled();
  });

  test("relative import hitting a named wrapper triggers parse with context", async () => {
    const wrapper = {
      name: "track",
      methodKind: "capture",
      posthogMethod: "capture",
      classification: { kind: "pass-through", paramIndex: 0 },
      isNamedExport: true,
      isDefaultExport: false,
    };
    const { deps, parseSpy, findImportsSpy, getWrappersSpy } = makeDeps({
      findImportsInSource: async () => [
        {
          localName: "track",
          importedName: "track",
          resolvedAbsPath: "/tmp/telemetry.ts",
        },
      ],
      getWrappersForFile: async () => [wrapper],
    });
    const result = await enrichFileForAgent(
      deps,
      "/tmp/app.ts",
      'import { track } from "./telemetry";\ntrack("x");',
    );
    expect(result).toBe("enriched content");
    expect(findImportsSpy).toHaveBeenCalled();
    expect(getWrappersSpy).toHaveBeenCalledWith("/tmp/telemetry.ts");
    expect(parseSpy).toHaveBeenCalledWith(
      expect.any(String),
      expect.any(String),
      expect.objectContaining({
        wrappersByLocalName: expect.any(Map),
      }),
    );
    const ctxArg = parseSpy.mock.calls[0][2] as {
      wrappersByLocalName: Map<string, unknown>;
    };
    expect(ctxArg.wrappersByLocalName.get("track")).toEqual(wrapper);
  });

  test("file with posthog literal and no relative imports skips import resolution", async () => {
    const { deps, findImportsSpy, parseSpy } = makeDeps({});
    await enrichFileForAgent(deps, "/tmp/code.ts", "posthog.capture('x');");
    expect(findImportsSpy).not.toHaveBeenCalled();
    expect(parseSpy).toHaveBeenCalled();
  });

  test("file with only bare-package imports does not trigger import resolution", async () => {
    const { deps, findImportsSpy } = makeDeps({});
    const content = [
      'import React from "react";',
      'import { useState } from "react";',
      'import posthog from "posthog-js";',
      "posthog.capture('x');",
    ].join("\n");
    await enrichFileForAgent(deps, "/tmp/page.tsx", content);
    expect(findImportsSpy).not.toHaveBeenCalled();
  });

  test("file with direct posthog AND wrapper imports gets both enriched", async () => {
    const wrapper = {
      name: "track",
      methodKind: "capture",
      posthogMethod: "capture",
      classification: { kind: "pass-through", paramIndex: 0 },
      isNamedExport: true,
      isDefaultExport: false,
    };
    const { deps, findImportsSpy, parseSpy } = makeDeps({
      findImportsInSource: async () => [
        {
          localName: "track",
          importedName: "track",
          resolvedAbsPath: "/tmp/utils.ts",
        },
      ],
      getWrappersForFile: async () => [wrapper],
    });
    const content = [
      'import posthog from "posthog-js";',
      'import { track } from "./utils";',
      "posthog.capture('direct');",
      'track("wrapper_call");',
    ].join("\n");
    await enrichFileForAgent(deps, "/tmp/page.tsx", content);
    expect(findImportsSpy).toHaveBeenCalled();
    const ctx = parseSpy.mock.calls[0][2] as {
      wrappersByLocalName: Map<string, unknown>;
    };
    expect(ctx.wrappersByLocalName.get("track")).toEqual(wrapper);
  });

  test("returns null when getApiKey yields empty string", async () => {
    const { deps, enrichFromApiSpy } = makeDeps({ getApiKey: () => "" });
    const result = await enrichFileForAgent(
      deps,
      "/tmp/code.ts",
      "posthog.capture('x');",
    );
    expect(result).toBeNull();
    expect(enrichFromApiSpy).not.toHaveBeenCalled();
  });

  test("returns null when toInlineComments produces no change", async () => {
    const original = "posthog.capture('x');";
    const { deps } = makeDeps({ toInlineCommentsReturn: original });
    const result = await enrichFileForAgent(deps, "/tmp/code.ts", original);
    expect(result).toBeNull();
  });

  test("returns null and logs debug when enricher throws", async () => {
    const logger = { debug: vi.fn() };
    const { deps } = makeDeps({ parseRejects: new Error("boom") });
    deps.logger = logger as unknown as FileEnrichmentDeps["logger"];
    const result = await enrichFileForAgent(
      deps,
      "/tmp/code.ts",
      "posthog.capture('x');",
    );
    expect(result).toBeNull();
    expect(logger.debug).toHaveBeenCalledWith(
      "File enrichment failed",
      expect.objectContaining({ filePath: "/tmp/code.ts" }),
    );
  });

  test("returns enriched string when happy path completes", async () => {
    const { deps, enrichFromApiSpy } = makeDeps({
      toInlineCommentsReturn: "posthog.capture('x'); // [PostHog] Event: \"x\"",
    });
    const result = await enrichFileForAgent(
      deps,
      "/tmp/code.ts",
      "posthog.capture('x');",
    );
    expect(result).toBe("posthog.capture('x'); // [PostHog] Event: \"x\"");
    expect(enrichFromApiSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        apiKey: "phx_test",
        host: "https://test.posthog.com",
        projectId: 1,
      }),
    );
  });
});
