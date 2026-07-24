import { formatMention, splitMentionSegments } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import type { Node as PmNode } from "@tiptap/pm/model";
import type { JSONContent } from "@tiptap/react";

export type ComposerMentionCandidate =
  | { kind: "agent" }
  | { kind: "member"; member: UserBasic };

/** Members matching the query, best-first: name prefix, word prefix, email, substring. */
export function filterMentionCandidates(
  members: UserBasic[],
  query: string,
  limit = 8,
): UserBasic[] {
  const q = query.trim().toLowerCase();
  const scored: Array<{ member: UserBasic; score: number }> = [];
  for (const member of members) {
    const name = userDisplayName(member).toLowerCase();
    const email = member.email.toLowerCase();
    let score: number | null = null;
    if (!q || name.startsWith(q)) score = 0;
    else if (name.split(/\s+/).some((word) => word.startsWith(q))) score = 1;
    else if (email.startsWith(q)) score = 2;
    else if (name.includes(q) || email.includes(q)) score = 3;
    if (score !== null) scored.push({ member, score });
  }
  return scored
    .sort(
      (a, b) =>
        a.score - b.score ||
        userDisplayName(a.member).localeCompare(userDisplayName(b.member)),
    )
    .slice(0, limit)
    .map((entry) => entry.member);
}

export function filterComposerMentionCandidates(
  members: UserBasic[],
  query: string,
  includeAgent: boolean,
  limit = 8,
): ComposerMentionCandidate[] {
  const normalizedQuery = query.trim().toLowerCase();
  const includeAgentCandidate =
    includeAgent && (!normalizedQuery || "agent".startsWith(normalizedQuery));
  const memberLimit = Math.max(0, limit - (includeAgentCandidate ? 1 : 0));
  return [
    ...(includeAgentCandidate ? [{ kind: "agent" as const }] : []),
    ...filterMentionCandidates(members, query, memberLimit).map(
      (member): ComposerMentionCandidate => ({ kind: "member", member }),
    ),
  ];
}

/** Serialize the composer's editor doc back to content with inline mention tokens. */
export function docToContent(doc: PmNode): string {
  const lines: string[] = [];
  doc.forEach((block) => {
    let line = "";
    block.forEach((child) => {
      if (child.type.name === "mention") {
        line += formatMention(child.attrs.label, child.attrs.id);
      } else if (child.type.name === "hardBreak") {
        line += "\n";
      } else {
        line += child.text ?? "";
      }
    });
    lines.push(line);
  });
  return lines.join("\n");
}

export function contentToDoc(content: string): JSONContent {
  return {
    type: "doc",
    content: content.split("\n").map((line) => {
      const children = splitMentionSegments(line).flatMap<JSONContent>(
        (segment) =>
          segment.type === "mention"
            ? [
                {
                  type: "mention",
                  attrs: { id: segment.email, label: segment.name },
                },
              ]
            : segment.text
              ? [{ type: "text", text: segment.text }]
              : [],
      );
      return children.length
        ? { type: "paragraph", content: children }
        : { type: "paragraph" };
    }),
  };
}
