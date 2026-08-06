import { describe, expect, it, vi } from "vitest";
import {
  fetchDesktopReleases,
  toFeedReleases,
} from "./build-releases-feed.mjs";

const release = (tagName, overrides = {}) => ({
  tag_name: tagName,
  name: `Release ${tagName}`,
  body: `Notes for ${tagName}`,
  draft: false,
  prerelease: false,
  published_at: "2026-08-06T00:00:00Z",
  html_url: `https://github.com/PostHog/posthog/releases/tag/${tagName}`,
  ...overrides,
});

const response = (releases, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => releases,
});

describe("toFeedReleases", () => {
  it("keeps published desktop releases and strips the desktop tag prefix", () => {
    const releases = toFeedReleases([
      release("desktop-v0.60.58", { prerelease: true }),
      release("desktop-v0.60.57", { draft: true }),
      release("agent-v2.4.10"),
      release("posthog-cli/v0.10.0"),
    ]);

    expect(releases).toEqual([
      {
        version: "0.60.58",
        name: "Release desktop-v0.60.58",
        notes: "Notes for desktop-v0.60.58",
        date: "2026-08-06T00:00:00Z",
        isPrerelease: true,
        htmlUrl:
          "https://github.com/PostHog/posthog/releases/tag/desktop-v0.60.58",
      },
    ]);
  });
});

describe("fetchDesktopReleases", () => {
  it("paginates past unrelated monorepo releases", async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) =>
      release(`agent-skills-v0.${index}.0`),
    );
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response(firstPage))
      .mockResolvedValueOnce(response([release("desktop-v0.60.58")]));

    const releases = await fetchDesktopReleases(fetchImpl);

    expect(releases.map(({ version }) => version)).toEqual(["0.60.58"]);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(fetchImpl.mock.calls[1][0]).toContain("page=2");
  });

  it("returns at most the 30 newest desktop releases", async () => {
    const apiReleases = Array.from({ length: 100 }, (_, index) =>
      release(`desktop-v0.60.${100 - index}`),
    );
    const fetchImpl = vi.fn().mockResolvedValue(response(apiReleases));

    const releases = await fetchDesktopReleases(fetchImpl);

    expect(releases).toHaveLength(30);
    expect(releases[0].version).toBe("0.60.100");
    expect(releases[29].version).toBe("0.60.71");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
