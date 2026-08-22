import { ApiRequestError } from "@posthog/api-client/fetcher";
import { describe, expect, it } from "vitest";
import {
  describeGithubConnectError,
  describeIntegrationDisconnectError,
  isAlreadyDisconnectedError,
  isGithubConnectPendingApproval,
} from "./connectErrors";

describe("describeIntegrationDisconnectError", () => {
  it.each([
    [
      "403 explains the admin gate",
      new ApiRequestError(403, "{}", { detail: "nope" }),
      "Only project admins can disconnect this integration.",
    ],
    [
      "validation detail is shown verbatim",
      new ApiRequestError(400, "{}", {
        detail:
          "This integration is used by enabled data pipelines: Slack alerts.",
      }),
      "This integration is used by enabled data pipelines: Slack alerts.",
    ],
    [
      "plain error keeps its message",
      new Error("network down"),
      "network down",
    ],
    ["unknown falls back", "nope", "Failed to disconnect."],
  ])("%s", (_name, error, expected) => {
    expect(
      describeIntegrationDisconnectError(error, "Failed to disconnect."),
    ).toBe(expected);
  });
});

describe("isAlreadyDisconnectedError", () => {
  it.each([
    [
      "typed 404",
      new ApiRequestError(
        404,
        '{"detail":"No GitHub integration found for this installation."}',
      ),
      true,
    ],
    [
      "legacy message with status",
      new Error(
        'Failed request: [404] {"detail":"No GitHub integration found for this installation."}',
      ),
      true,
    ],
    [
      "legacy status text",
      new Error("Failed to disconnect GitHub integration: Not Found"),
      true,
    ],
    ["typed 500", new ApiRequestError(500, "boom"), false],
    [
      "typed 400 whose blocker detail reads like a 404",
      new ApiRequestError(
        400,
        '{"detail":"Workflow not found alerts uses it"}',
      ),
      false,
    ],
    ["unrelated error", new Error("network down"), false],
    ["not an error", "nope", false],
  ])("%s", (_name, error, expected) => {
    expect(isAlreadyDisconnectedError(error)).toBe(expected);
  });
});

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

describe("isGithubConnectPendingApproval", () => {
  it.each([
    ["github_install_pending", true],
    ["access_denied", false],
    [null, false],
    [undefined, false],
  ])("code %s -> %s", (code, expected) => {
    expect(isGithubConnectPendingApproval(code)).toBe(expected);
  });
});
