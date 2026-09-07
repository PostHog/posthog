import { describe, expect, it } from "vitest";
import {
  DesktopPreviewConfigError,
  desktopPreviewIdentity,
  parseDesktopPreviewManifest,
} from "./desktop-preview";

// Synthetic example from reserved domains; no real host or credential.
const validManifest = {
  schemaVersion: 1,
  kind: "desktop-preview",
  repository: "PostHog/posthog",
  prNumber: 123,
  commitSha: "1111111111111111111111111111111111111111",
  backendOrigin: "https://preview.example.com",
  gatewayBaseUrl: "https://preview.example.com/llm-gateway/",
  oauthClientId: "example-public-client-id-1234",
};

describe("parseDesktopPreviewManifest", () => {
  it("accepts a valid manifest", () => {
    const parsed = parseDesktopPreviewManifest(validManifest);
    expect(parsed.prNumber).toBe(123);
    expect(parsed.backendOrigin).toBe("https://preview.example.com");
    expect(parsed.gatewayBaseUrl).toBe(
      "https://preview.example.com/llm-gateway",
    );
  });

  it("accepts a preview without a gateway", () => {
    const parsed = parseDesktopPreviewManifest({
      ...validManifest,
      gatewayBaseUrl: null,
    });
    expect(parsed.gatewayBaseUrl).toBeNull();
  });

  it.each([
    "http://preview.example.com/llm-gateway",
    "https://user:pw@preview.example.com/llm-gateway",
    "https://preview.example.com/llm-gateway?x=1",
  ])("rejects the gateway URL %s", (gatewayBaseUrl) => {
    expect(() =>
      parseDesktopPreviewManifest({ ...validManifest, gatewayBaseUrl }),
    ).toThrow(DesktopPreviewConfigError);
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
});

describe("desktopPreviewIdentity", () => {
  it("derives one stable identity per PR", () => {
    const identity = desktopPreviewIdentity(
      parseDesktopPreviewManifest(validManifest),
    );
    expect(identity).toEqual({
      productName: "PostHog Preview PR 123",
      appId: "com.posthog.array.preview.pr123",
      slug: "posthog-code-preview-pr-123",
      fileName: "PostHog-Preview-PR-123",
    });
  });

  it("derives a distinct identity for a different PR", () => {
    const a = desktopPreviewIdentity(
      parseDesktopPreviewManifest(validManifest),
    );
    const b = desktopPreviewIdentity(
      parseDesktopPreviewManifest({ ...validManifest, prNumber: 124 }),
    );
    expect(b.slug).not.toBe(a.slug);
    expect(b.appId).not.toBe(a.appId);
  });
});
