import { ApiRequestError } from "@posthog/api-client/fetcher";
import { LoopsApiError } from "@posthog/api-client/loops";
import { describe, expect, it } from "vitest";
import { isLoopNotFoundError } from "./useLoop";

describe("isLoopNotFoundError", () => {
  it.each([
    {
      name: "loops API 404",
      error: new LoopsApiError("get", "/loops/x/", 404, null),
      expected: true,
    },
    {
      name: "workflow API 404",
      error: new ApiRequestError(404, "{}"),
      expected: true,
    },
    {
      name: "loops API 500",
      error: new LoopsApiError("get", "/loops/x/", 500, null),
      expected: false,
    },
    {
      name: "workflow API 403",
      error: new ApiRequestError(403, "{}"),
      expected: false,
    },
    { name: "network error", error: new Error("offline"), expected: false },
    { name: "no error", error: null, expected: false },
  ])("$name returns $expected", ({ error, expected }) => {
    expect(isLoopNotFoundError(error)).toBe(expected);
  });
});
