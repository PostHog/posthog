import type { AvailableSuggestedReviewer } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  buildSuggestedReviewerFilterOptions,
  getSuggestedReviewerDisplayName,
} from "./filterOptions";

function makeReviewer(
  overrides: Partial<AvailableSuggestedReviewer> = {},
): AvailableSuggestedReviewer {
  return {
    uuid: "reviewer-1",
    name: "Alice Jones",
    email: "alice@example.com",
    github_login: "alicejones",
    ...overrides,
  };
}

describe("getSuggestedReviewerDisplayName", () => {
  it("returns name when present", () => {
    expect(
      getSuggestedReviewerDisplayName({
        ...makeReviewer({ name: "Alice Jones" }),
        isMe: false,
      }),
    ).toBe("Alice Jones");
  });

  it("falls back to email when name is missing", () => {
    expect(
      getSuggestedReviewerDisplayName({
        ...makeReviewer({
          name: "",
          email: "fallback@example.com",
        }),
        isMe: false,
      }),
    ).toBe("fallback@example.com");
  });

  it("falls back to Unknown user when name and email are missing", () => {
    expect(
      getSuggestedReviewerDisplayName({
        ...makeReviewer({
          name: "",
          email: "",
        }),
        isMe: false,
      }),
    ).toBe("Unknown user");
  });

  it("appends Me for the pinned current user", () => {
    expect(
      getSuggestedReviewerDisplayName({
        ...makeReviewer({ name: "Boss Person" }),
        isMe: true,
      }),
    ).toBe("Boss Person (Me)");
  });
});

describe("buildSuggestedReviewerFilterOptions", () => {
  it("pins the current user to the top and marks them as me", () => {
    const me = {
      uuid: "me-id",
      first_name: "Boss",
      last_name: "Person",
      email: "boss@example.com",
    };
    const options = buildSuggestedReviewerFilterOptions(
      [
        makeReviewer({
          uuid: "other-id",
          name: "Alice Jones",
        }),
      ],
      me,
    );

    expect(options).toHaveLength(2);
    expect(options[0]).toMatchObject({
      uuid: "me-id",
      name: "Boss Person",
      isMe: true,
      showSeparatorBelow: true,
    });
    expect(getSuggestedReviewerDisplayName(options[0])).toBe(
      "Boss Person (Me)",
    );
    expect(options[1]).toMatchObject({
      uuid: "other-id",
      name: "Alice Jones",
      isMe: false,
      showSeparatorBelow: false,
    });
  });

  it("deduplicates the current user if already present in backend results", () => {
    const me = {
      uuid: "me-id",
      first_name: "Boss",
      last_name: "Person",
      email: "boss@example.com",
    };
    const options = buildSuggestedReviewerFilterOptions(
      [
        makeReviewer({
          uuid: "me-id",
          name: "Old Name",
          email: "old@example.com",
        }),
        makeReviewer({
          uuid: "other-id",
          name: "Alice Jones",
        }),
      ],
      me,
    );

    expect(options.map((option) => option.uuid)).toEqual(["me-id", "other-id"]);
    expect(options[0]).toMatchObject({
      uuid: "me-id",
      name: "Boss Person",
      email: "boss@example.com",
      isMe: true,
    });
  });

  it("sorts backend reviewers alphabetically by name", () => {
    const options = buildSuggestedReviewerFilterOptions(
      [
        makeReviewer({ uuid: "c", name: "Charlie Zebra" }),
        makeReviewer({ uuid: "a", name: "Alice Jones" }),
        makeReviewer({ uuid: "b", name: "Bob Smith" }),
      ],
      null,
    );

    expect(options.map((option) => option.uuid)).toEqual(["a", "b", "c"]);
    expect(options.map((option) => option.name)).toEqual([
      "Alice Jones",
      "Bob Smith",
      "Charlie Zebra",
    ]);
  });

  it("uses email and uuid as stable alphabetical tie-breakers", () => {
    const options = buildSuggestedReviewerFilterOptions(
      [
        makeReviewer({ uuid: "b", name: "", email: "b@example.com" }),
        makeReviewer({ uuid: "a", name: "", email: "a@example.com" }),
        makeReviewer({ uuid: "c", name: "", email: "a@example.com" }),
      ],
      null,
    );

    expect(options.map((option) => option.uuid)).toEqual(["a", "c", "b"]);
  });

  it("returns backend reviewers unchanged when there is no current user", () => {
    const reviewers = [
      makeReviewer({ uuid: "b", name: "Bob Smith" }),
      makeReviewer({ uuid: "a", name: "Alice Jones" }),
    ];

    const options = buildSuggestedReviewerFilterOptions(reviewers, null);

    expect(options).toHaveLength(2);
    expect(options[0]).toMatchObject({
      uuid: "a",
      name: "Alice Jones",
      isMe: false,
    });
    expect(options[1]).toMatchObject({
      uuid: "b",
      name: "Bob Smith",
      isMe: false,
    });
  });
});
