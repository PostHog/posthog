import { describe, expect, it } from "vitest";
import {
  assertNoPreviewConfig,
  DesktopPreviewConfigError,
  desktopPreviewIdentity,
  PREVIEW_DEPLOYMENT_METADATA_PATH,
  parseDesktopPreviewManifest,
  previewDeploymentMetadataSchema,
} from "./desktop-preview";

// Synthetic example from reserved domains; no real host or credential.
const validManifest = {
  schemaVersion: 1,
  kind: "desktop-preview",
  repository: "PostHog/posthog",
  prNumber: 123,
  commitSha: "1111111111111111111111111111111111111111",
  backendOrigin: "https://preview.example.com",
  oauthClientId: "example-public-client-id-1234",
  gateway: { kind: "unavailable", reason: "Gateway has not been configured" },
  featureFlags: {},
  capabilities: [],
};

describe("parseDesktopPreviewManifest", () => {
  it("accepts a valid manifest", () => {
    const parsed = parseDesktopPreviewManifest(validManifest);
    expect(parsed.prNumber).toBe(123);
    expect(parsed.backendOrigin).toBe("https://preview.example.com");
  });

  it("rejects an unknown schema version", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        schemaVersion: 2,
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects a wrong kind", () => {
    expect(() =>
      parseDesktopPreviewManifest({ ...validManifest, kind: "release" }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects a partial or malformed commit SHA", () => {
    expect(() =>
      parseDesktopPreviewManifest({ ...validManifest, commitSha: "abc123" }),
    ).toThrow(DesktopPreviewConfigError);
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        commitSha: "Z111111111111111111111111111111111111111",
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects a malformed PR number", () => {
    expect(() =>
      parseDesktopPreviewManifest({ ...validManifest, prNumber: 0 }),
    ).toThrow(DesktopPreviewConfigError);
    expect(() =>
      parseDesktopPreviewManifest({ ...validManifest, prNumber: 12.5 }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects non-HTTPS backend origins", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        backendOrigin: "http://preview.example.com",
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects an origin with credentials", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        backendOrigin: "https://user:secret@preview.example.com",
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects an origin with a path, query, or fragment", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        backendOrigin: "https://preview.example.com/pr/123",
      }),
    ).toThrow(DesktopPreviewConfigError);
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        backendOrigin: "https://preview.example.com?x=1",
      }),
    ).toThrow(DesktopPreviewConfigError);
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        backendOrigin: "https://preview.example.com/#/",
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects unexpected fields", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        clientSecret: "must-not-be-accepted",
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects unknown feature-flag values", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        featureFlags: { "some-flag": "true" },
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects a non-HTTPS gateway base URL", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        gateway: { kind: "ai-gateway", baseUrl: "http://gateway.example.com" },
      }),
    ).toThrow(DesktopPreviewConfigError);
  });

  it("rejects a gateway base URL with credentials", () => {
    expect(() =>
      parseDesktopPreviewManifest({
        ...validManifest,
        gateway: {
          kind: "ai-gateway",
          baseUrl: "https://key@gateway.example.com",
        },
      }),
    ).toThrow(DesktopPreviewConfigError);
  });
});

describe("desktopPreviewIdentity", () => {
  it("derives one stable identity per PR", () => {
    const identity = desktopPreviewIdentity(
      parseDesktopPreviewManifest(validManifest),
    );
    expect(identity.productName).toBe("PostHog Preview PR 123");
    expect(identity.appId).toBe("com.posthog.array.preview.pr123");
    expect(identity.scheme).toBe("posthog-code-preview-pr-123");
    expect(identity.redirectUri).toBe("posthog-code-preview-pr-123://callback");
    expect(identity.userDataDirName).toBe("posthog-code-preview-pr-123");
  });

  it("derives a distinct identity for a different PR", () => {
    const a = desktopPreviewIdentity(
      parseDesktopPreviewManifest(validManifest),
    );
    const b = desktopPreviewIdentity(
      parseDesktopPreviewManifest({ ...validManifest, prNumber: 124 }),
    );
    expect(b.scheme).not.toBe(a.scheme);
    expect(b.appId).not.toBe(a.appId);
    expect(b.redirectUri).not.toBe(a.redirectUri);
  });
});

describe("assertNoPreviewConfig", () => {
  it("passes when no preview manifest is supplied", () => {
    expect(() => assertNoPreviewConfig(null)).not.toThrow();
  });

  it("fails closed when a release build receives preview configuration", () => {
    expect(() =>
      assertNoPreviewConfig(parseDesktopPreviewManifest(validManifest)),
    ).toThrow(DesktopPreviewConfigError);
  });
});

describe("previewDeploymentMetadataSchema", () => {
  it("accepts the served metadata document shape", () => {
    const parsed = previewDeploymentMetadataSchema.safeParse({
      schemaVersion: 1,
      prNumber: 123,
      commitSha: "1111111111111111111111111111111111111111",
      deploymentGeneration: 4,
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects a stale document that carries the SPA instead of JSON", () => {
    const parsed = previewDeploymentMetadataSchema.safeParse(
      "<!doctype html><html></html>",
    );
    expect(parsed.success).toBe(false);
  });

  it("rejects unexpected fields in the metadata document", () => {
    const parsed = previewDeploymentMetadataSchema.safeParse({
      schemaVersion: 1,
      prNumber: 123,
      commitSha: "1111111111111111111111111111111111111111",
      deploymentGeneration: 4,
      extra: true,
    });
    expect(parsed.success).toBe(false);
  });
});

describe("PREVIEW_DEPLOYMENT_METADATA_PATH", () => {
  it("points at the preview static asset route", () => {
    expect(PREVIEW_DEPLOYMENT_METADATA_PATH).toBe(
      "/static/desktop-preview/deployment.json",
    );
  });
});
