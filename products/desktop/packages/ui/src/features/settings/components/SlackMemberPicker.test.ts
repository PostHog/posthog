import { ApiRequestError } from "@posthog/api-client/fetcher";
import { describe, expect, it } from "vitest";
import { slackMemberErrorMessage } from "./SlackMemberPicker";

describe("slackMemberErrorMessage", () => {
  it("surfaces the server detail so an inactive workspace is not read as empty", () => {
    const detail = "Reconnect Slack to load channels and pick a destination.";
    const error = new ApiRequestError(400, JSON.stringify({ detail }), {
      detail,
    });
    expect(slackMemberErrorMessage(error)).toBe(detail);
  });

  it.each([
    ["a non-API error", new Error("network down")],
    ["an API error with no detail body", new ApiRequestError(500, "{}", {})],
  ])("falls back to a retry message for %s", (_label, error) => {
    expect(slackMemberErrorMessage(error)).toBe(
      "Couldn't load members. Try again in a moment.",
    );
  });
});
