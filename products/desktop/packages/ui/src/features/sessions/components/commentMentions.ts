import { splitMentionSegments } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";

export function mentionIdsFromContent(
  content: string,
  members: UserBasic[],
): number[] {
  const emails = new Set<string>();
  for (const segment of splitMentionSegments(content)) {
    if (segment.type === "mention") emails.add(segment.email.toLowerCase());
  }
  return members
    .filter((member) => emails.has(member.email.toLowerCase()))
    .map((member) => member.id);
}
