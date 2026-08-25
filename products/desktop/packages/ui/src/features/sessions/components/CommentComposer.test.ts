import { formatMention } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { mentionIdsFromContent } from "./commentMentions";

const members = [
  { id: 1, uuid: "user-1", email: "abe@posthog.com", first_name: "Abe" },
  { id: 2, uuid: "user-2", email: "max@posthog.com", first_name: "Max" },
] as UserBasic[];

describe("mentionIdsFromContent", () => {
  it("returns the user IDs represented by Thread mention tokens", () => {
    const content = `Please review ${formatMention("Abe", "abe@posthog.com")}`;
    expect(mentionIdsFromContent(content, members)).toEqual([1]);
  });

  it("does not notify plain-text email addresses", () => {
    expect(mentionIdsFromContent("Email max@posthog.com", members)).toEqual([]);
  });
});
