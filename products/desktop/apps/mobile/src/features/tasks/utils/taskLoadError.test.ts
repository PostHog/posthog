import { ApiRequestError } from "@posthog/api-client/fetcher";
import { describe, expect, it } from "vitest";
import { classifyTaskLoadError } from "./taskLoadError";

describe("classifyTaskLoadError", () => {
  it.each([
    {
      name: "an explicit 404 from the API",
      error: new ApiRequestError(404, '{"detail":"Not found."}'),
      expected: "not_found" as const,
    },
    {
      name: "a 403 the token isn't authorized for",
      error: new ApiRequestError(403, '{"detail":"Forbidden."}'),
      expected: "other" as const,
    },
    {
      name: "a server error",
      error: new ApiRequestError(500, '{"error":"500"}'),
      expected: "other" as const,
    },
    {
      name: "a network failure that never reached the server",
      error: new Error("Network request failed for GET https://us.posthog.com"),
      expected: "other" as const,
    },
    {
      name: "a thrown non-error",
      error: "boom",
      expected: "other" as const,
    },
    { name: "nothing at all", error: undefined, expected: "other" as const },
  ])("classifies $name as $expected", ({ error, expected }) => {
    expect(classifyTaskLoadError(error)).toBe(expected);
  });
});
