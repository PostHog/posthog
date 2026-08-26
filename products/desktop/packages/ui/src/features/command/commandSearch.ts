import type { CommandSection } from "@posthog/ui/features/command/useSearchSections";

export const RECENT_COMMAND_LIMIT = 5;

export function addRecentCommand<T extends { id: string }>(
  recentCommands: T[],
  command: T,
): T[] {
  return [
    command,
    ...recentCommands.filter(
      (recentCommand) => recentCommand.id !== command.id,
    ),
  ].slice(0, RECENT_COMMAND_LIMIT);
}

export function matchesCommandSearch(
  command: { label: string; keywords?: string },
  query: string,
): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;

  const haystack = `${command.label} ${command.keywords ?? ""}`.toLowerCase();
  return haystack.includes(normalizedQuery);
}

export function prioritizeExactCommandMatches(
  sections: CommandSection[],
  query: string,
): CommandSection[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return sections;

  const exactMatches = sections.flatMap((section) =>
    section.items.filter(
      (item) => item.label.trim().toLowerCase() === normalizedQuery,
    ),
  );
  if (exactMatches.length === 0) return sections;

  return [
    { label: "Exact matches", items: exactMatches },
    ...sections
      .map((section) => ({
        ...section,
        items: section.items.filter(
          (item) => item.label.trim().toLowerCase() !== normalizedQuery,
        ),
      }))
      .filter((section) => section.items.length > 0),
  ];
}
