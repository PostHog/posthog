import { describe, expect, it, vi } from "vitest";
import { fetchExistingReleases, mergeRelease } from "./build-releases-feed.mjs";

const entry = (version, overrides = {}) => ({
  version,
  name: `v${version}`,
  notes: `Notes for ${version}`,
  date: "2026-08-06T00:00:00Z",
  isPrerelease: false,
  htmlUrl: `https://github.com/PostHog/posthog/releases/tag/desktop-v${version}`,
  ...overrides,
});

const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

describe("mergeRelease", () => {
  it("prepends the new release to the existing feed", () => {
    const merged = mergeRelease(
      [entry("0.60.57"), entry("0.60.56")],
      entry("0.60.58"),
    );

    expect(merged.map(({ version }) => version)).toEqual([
      "0.60.58",
      "0.60.57",
      "0.60.56",
    ]);
  });

  it("replaces an existing entry on a re-run of the same version", () => {
    const merged = mergeRelease(
      [entry("0.60.58", { notes: "stale" }), entry("0.60.57")],
      entry("0.60.58", { notes: "fresh" }),
    );

    expect(merged.map(({ version }) => version)).toEqual([
      "0.60.58",
      "0.60.57",
    ]);
    expect(merged[0].notes).toBe("fresh");
  });

  it("caps the feed at the 30 newest releases", () => {
    const existing = Array.from({ length: 40 }, (_, index) =>
      entry(`0.60.${40 - index}`),
    );

    const merged = mergeRelease(existing, entry("0.60.41"));

    expect(merged).toHaveLength(30);
    expect(merged[0].version).toBe("0.60.41");
    expect(merged[29].version).toBe("0.60.12");
  });
});

describe("fetchExistingReleases", () => {
  it("returns the published releases", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ releases: [entry("0.60.57")] }));

    const releases = await fetchExistingReleases(fetchImpl);

    expect(releases.map(({ version }) => version)).toEqual(["0.60.57"]);
  });

  it.each([[403], [404]])(
    "treats a %i (feed never published) as an empty feed",
    async (status) => {
      const fetchImpl = vi.fn().mockResolvedValue(response(null, status));

      await expect(fetchExistingReleases(fetchImpl)).resolves.toEqual([]);
    },
  );

  it("throws on other fetch failures instead of wiping history", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(null, 500));

    await expect(fetchExistingReleases(fetchImpl)).rejects.toThrow(
      "Release feed fetch failed: 500",
    );
  });

  it.each([[{}], [{ releases: null }], [null]])(
    "throws on a 200 response without a releases array (%o) instead of wiping history",
    async (body) => {
      const fetchImpl = vi.fn().mockResolvedValue(response(body));

      await expect(fetchExistingReleases(fetchImpl)).rejects.toThrow(
        "Release feed response has no releases array",
      );
    },
  );
});
