import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadPreviewManifest } from "./preview-config.mts";

let directory: string;
const manifest = {
  schemaVersion: 1,
  kind: "desktop-preview",
  repository: "PostHog/posthog",
  prNumber: 123,
  commitSha: "1".repeat(40),
  backendOrigin: "https://preview.example.com",
  gatewayBaseUrl: "https://preview.example.com/llm-gateway",
  oauthClientId: "example-public-client-id",
};

beforeEach(() => {
  directory = mkdtempSync(path.join(tmpdir(), "preview-config-"));
  const filename = path.join(directory, "manifest.json");
  writeFileSync(filename, JSON.stringify(manifest));
  vi.stubEnv("POSTHOG_DESKTOP_PREVIEW_CONFIG", filename);
  vi.stubEnv("POSTHOG_DESKTOP_PREVIEW_PR", "123");
  vi.stubEnv("POSTHOG_DESKTOP_PREVIEW_SHA", manifest.commitSha);
  vi.stubEnv(
    "POSTHOG_DESKTOP_PREVIEW_EXPECTED_ORIGIN",
    "https://preview.example.com/",
  );
});
afterEach(() => {
  vi.unstubAllEnvs();
  rmSync(directory, { recursive: true });
});

describe("loadPreviewManifest", () => {
  it("returns the validated manifest", () => {
    expect(loadPreviewManifest()).toEqual(manifest);
  });
  it.each([
    ["POSTHOG_DESKTOP_PREVIEW_PR", "124"],
    ["POSTHOG_DESKTOP_PREVIEW_SHA", "2".repeat(40)],
  ])("rejects inconsistent %s", (name, value) => {
    vi.stubEnv(name, value);
    expect(() => loadPreviewManifest()).toThrow();
  });
  it("rejects a manifest whose origin the trusted deploy output does not vouch for", () => {
    vi.stubEnv(
      "POSTHOG_DESKTOP_PREVIEW_EXPECTED_ORIGIN",
      "https://other-preview.example.com/",
    );
    expect(() => loadPreviewManifest()).toThrow();
  });
  it("refuses a preview build with no trusted origin", () => {
    vi.stubEnv("POSTHOG_DESKTOP_PREVIEW_EXPECTED_ORIGIN", "");
    expect(() => loadPreviewManifest()).toThrow();
  });
  it("keeps an ordinary build free of preview configuration", () => {
    vi.stubEnv("POSTHOG_DESKTOP_PREVIEW_CONFIG", "");
    expect(loadPreviewManifest()).toBeNull();
  });
});
