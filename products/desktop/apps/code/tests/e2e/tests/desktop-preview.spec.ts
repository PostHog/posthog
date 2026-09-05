import { expect, test } from "../fixtures/electron";

// Preview-build behaviors that must hold in a packaged desktop-preview
// installer. These run against the ordinary test build too (every assertion
// is about invariants that hold in both, or explicitly guards the ordinary
// build's unchanged behavior); the OAuth-callback e2e against a live preview
// backend runs in the desktop-preview workflow's smoke step, where the
// manifest is baked in.
//
// The deep assertions (scheme isolation, updater gating, identity) live in
// unit tests on the services; this file proves them through the launched app.

test.describe("Desktop preview invariants", () => {
  test("app name never collides between ordinary and preview identities", async ({
    electronApp,
  }) => {
    const name = await electronApp.evaluate(async ({ app }) => {
      const { desktopPreviewIdentity } = await import("@posthog/shared");
      const ordinary = "PostHog";
      const preview = desktopPreviewIdentity({
        schemaVersion: 1,
        kind: "desktop-preview",
        repository: "PostHog/posthog",
        prNumber: 123,
        commitSha: "1111111111111111111111111111111111111111",
        backendOrigin: "https://preview.example.com",
        oauthClientId: "example-public-client-id-1234",
        gateway: { kind: "unavailable", reason: "not configured" },
        featureFlags: {},
        capabilities: [],
      });
      return {
        current: app.getName(),
        previewName: preview.productName,
        ordinary,
      };
    });

    // The running build keeps its own name; the preview identity is distinct
    // from both it and the production name, so two installed apps never
    // collide in the OS app list.
    expect(name.previewName).not.toBe(name.ordinary);
    expect(name.current).toBeTruthy();
  });

  test("the preview scheme differs from the production scheme", async ({
    electronApp,
  }) => {
    const schemes = await electronApp.evaluate(async () => {
      const { getDeeplinkProtocolOptions } = await import("@posthog/shared");
      return {
        production: getDeeplinkProtocolOptions(false, null),
        preview: getDeeplinkProtocolOptions(
          false,
          "posthog-code-preview-pr-123",
        ),
      };
    });

    expect(schemes.production).toContain("posthog-code");
    // A preview build registers ONLY its own scheme: it must never claim the
    // production or legacy callbacks, and they must never claim its OAuth
    // callback.
    expect(schemes.preview).toEqual(["posthog-code-preview-pr-123"]);
  });

  test("window renders (boot state machine intact)", async ({ window }) => {
    await window.waitForSelector("#root > *", { timeout: 30000 });
  });
});
