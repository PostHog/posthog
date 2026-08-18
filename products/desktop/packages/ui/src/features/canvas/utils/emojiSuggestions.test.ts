import type { CommentEmoji } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  filterEmojiSuggestions,
  splitCustomEmojiSegments,
} from "./emojiSuggestions";

const customEmojis: CommentEmoji[] = [
  { name: "party_parrot", url: "https://emoji.slack-edge.com/parrot.gif" },
];

describe("emojiSuggestions", () => {
  it.each([
    ["wave", "👋"],
    ["waving_hand", "👋"],
    ["+1", "👍"],
  ])("finds the Unicode emoji for the %s shortcode", (query, expected) => {
    expect(filterEmojiSuggestions(query, [])[0]?.insertion).toBe(expected);
  });

  it("includes Slack custom emoji and keeps its shortcode as the insertion", () => {
    expect(filterEmojiSuggestions("party_par", customEmojis)[0]).toMatchObject({
      name: "party_parrot",
      insertion: ":party_parrot:",
      imageUrl: "https://emoji.slack-edge.com/parrot.gif",
    });
  });

  it("replaces only known custom shortcodes when rendering comment text", () => {
    expect(
      splitCustomEmojiSegments(
        "Ship it :party_parrot: but keep :unknown:",
        customEmojis,
      ),
    ).toEqual([
      { type: "text", text: "Ship it " },
      {
        type: "customEmoji",
        name: "party_parrot",
        url: "https://emoji.slack-edge.com/parrot.gif",
      },
      { type: "text", text: " but keep :unknown:" },
    ]);
  });
});
