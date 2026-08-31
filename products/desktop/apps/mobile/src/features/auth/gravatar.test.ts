import { describe, expect, it, vi } from "vitest";

vi.mock("expo-crypto", async () => {
  const { createHash } = await import("node:crypto");
  return {
    CryptoDigestAlgorithm: { SHA256: "SHA-256" },
    digestStringAsync: vi.fn(async (_algorithm: string, data: string) =>
      createHash("sha256").update(data).digest("hex"),
    ),
  };
});

import {
  buildGravatarUrl,
  mapProbeResultToStatus,
  profilePictureDescription,
} from "./gravatar";

describe("buildGravatarUrl", () => {
  it.each([
    {
      name: "hashes the email and asks for the default size with d=404",
      email: "user@example.com",
      size: undefined,
      expected:
        "https://www.gravatar.com/avatar/b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514?s=144&d=404",
    },
    {
      name: "lowercases and trims the email before hashing",
      email: "  TEST@Example.com ",
      size: undefined,
      expected:
        "https://www.gravatar.com/avatar/973dfe463ec85785f5f95af5ba3906eedb2d931c24e69824a89ea65dba4e813b?s=144&d=404",
    },
    {
      name: "requests the size the caller asks for",
      email: "user@example.com",
      size: 96,
      expected:
        "https://www.gravatar.com/avatar/b4c9a289323b21a01c3e940f150eb9b8c542587f1abfd8f0e1cc1ffc5e475514?s=96&d=404",
    },
  ])("$name", async ({ email, size, expected }) => {
    expect(await buildGravatarUrl(email, size)).toBe(expected);
  });

  it.each([
    { label: "null email", email: null },
    { label: "undefined email", email: undefined },
    { label: "empty string", email: "" },
    { label: "whitespace only", email: "   " },
  ])("returns undefined for a $label", async ({ email }) => {
    expect(await buildGravatarUrl(email)).toBeUndefined();
  });
});

describe("mapProbeResultToStatus", () => {
  it.each([
    { result: "loaded", status: "found" },
    { result: "failed", status: "missing" },
    { result: "unknown", status: "unknown" },
  ] as const)("maps $result to $status", ({ result, status }) => {
    expect(mapProbeResultToStatus(result)).toBe(status);
  });
});

describe("profilePictureDescription", () => {
  it("names Gravatar and the email in every state", () => {
    expect(profilePictureDescription("unknown", "sam@example.com")).toBe(
      "Checking Gravatar for sam@example.com",
    );
    expect(profilePictureDescription("found", "sam@example.com")).toContain(
      "Comes from Gravatar, matched to sam@example.com",
    );
    expect(profilePictureDescription("missing", "sam@example.com")).toContain(
      "Add one on Gravatar for sam@example.com",
    );
  });
});
