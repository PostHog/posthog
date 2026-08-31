import type { ContextWikiHealthFinding } from "@posthog/api-client/posthog-client";

export function groupFindings(
  findings: ContextWikiHealthFinding[],
): Record<string, ContextWikiHealthFinding[]> {
  return findings.reduce<Record<string, ContextWikiHealthFinding[]>>(
    (groups, finding) => {
      const group = groups[finding.category] ?? [];
      group.push(finding);
      groups[finding.category] = group;
      return groups;
    },
    {},
  );
}
