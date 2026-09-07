import { describe, expect, it } from "vitest";
import { sessionSubtitle } from "./sessionSubtitle";

describe("sessionSubtitle", () => {
  it.each([
    {
      name: "names the space without a hash",
      input: { space: "access-control", createdAt: null },
      expected: "access-control",
    },
    {
      name: "calls the private space what a reader sees",
      input: { space: "me", createdAt: null },
      expected: "personal",
    },
    {
      name: "orders repository, space, then age",
      input: {
        space: "access-control",
        repository: "example-org/webapp",
        createdAt: new Date(Date.now() - 60_000).toISOString(),
      },
      expected: "example-org/webapp · access-control · 1m",
    },
    {
      name: "says nothing when there is nothing to say",
      input: { space: null, repository: null, createdAt: null },
      expected: undefined,
    },
  ])("$name", ({ input, expected }) => {
    expect(sessionSubtitle(input)).toBe(expected);
  });
});
