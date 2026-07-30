import { describe, expect, it } from "vitest";
import { describeGithubConnectError } from "./connectErrors";

describe("describeGithubConnectError", () => {
  it("returns an empty string for no error", () => {
    expect(describeGithubConnectError(null)).toBe("");
  });

  it("maps a known error code to a friendly message", () => {
    expect(
      describeGithubConnectError({ message: "raw", code: "access_denied" }),
    ).toContain("declined access");
  });

  it("falls back to the raw message for unknown codes", () => {
    expect(
      describeGithubConnectError({ message: "raw message", code: "unknown" }),
    ).toBe("raw message");
  });
});
