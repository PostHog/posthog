import { afterEach, describe, expect, it, vi } from "vitest";
import { harnessExtensionFiles, harnessExtensions } from "./registry";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("harness extension opt-in", () => {
  it.each([
    ["POSTHOG_RTK", "rtk"],
    ["POSTHOG_ORCHESTRATION", "orchestration"],
  ])(
    "loads %s only when enabled in both harness entry points",
    (envName, name) => {
      vi.stubEnv(envName, "0");
      expect(
        harnessExtensions().map((extension) => extension.name),
      ).not.toContain(name);
      expect(
        harnessExtensionFiles().some((path) =>
          path.endsWith(`/${name}/index.js`),
        ),
      ).toBe(false);

      vi.stubEnv(envName, "1");
      expect(harnessExtensions().map((extension) => extension.name)).toContain(
        name,
      );
      expect(
        harnessExtensionFiles().some((path) =>
          path.endsWith(`/${name}/index.js`),
        ),
      ).toBe(true);
    },
  );
});
