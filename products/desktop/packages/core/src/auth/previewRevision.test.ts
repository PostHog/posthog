import { parseDesktopPreviewManifest } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { checkPreviewRevision } from "./previewRevision";

const preview = parseDesktopPreviewManifest({
  schemaVersion: 1,
  kind: "desktop-preview",
  repository: "PostHog/posthog",
  prNumber: 123,
  commitSha: "1".repeat(40),
  backendOrigin: "https://preview.example.com",
  oauthClientId: "example-public-client-id",
});
const metadata = {
  schemaVersion: 1,
  prNumber: 123,
  commitSha: "1".repeat(40),
  deploymentGeneration: 1,
};

describe("checkPreviewRevision", () => {
  it("accepts the matching revision and bypasses caches and redirects", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(metadata)));
    await expect(
      checkPreviewRevision(preview, fetchImpl),
    ).resolves.toBeUndefined();
    expect(fetchImpl).toHaveBeenCalledWith(
      `${preview.backendOrigin}/static/desktop-preview/deployment.json`,
      expect.objectContaining({ cache: "no-store", redirect: "error" }),
    );
  });
  it.each([
    ["different commit", { ...metadata, commitSha: "2".repeat(40) }],
    ["different PR", { ...metadata, prNumber: 124 }],
    ["unsupported schema", { ...metadata, schemaVersion: 2 }],
    ["null JSON", null],
    ["SPA fallback", "<html></html>"],
    ["missing fields", {}],
  ])("rejects %s", async (_, body) => {
    await expect(
      checkPreviewRevision(
        preview,
        vi.fn().mockResolvedValue(new Response(JSON.stringify(body))),
      ),
    ).rejects.toThrow();
  });
  it("rejects an unavailable backend without retrying mutations", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response("Waking", { status: 503 }));
    await expect(checkPreviewRevision(preview, fetchImpl)).rejects.toThrow(
      "Open it in your browser",
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
