/** The parts agents look for in CONTEXT.md; the editor offers each one that is missing. */
export interface BriefingSection {
  title: string;
  hint: string;
}

export const BRIEFING_SECTIONS: readonly BriefingSection[] = [
  {
    title: "What this is",
    hint: "The area, who it is for, what good looks like.",
  },
  {
    title: "How to work here",
    hint: "Conventions, review rules, how to test.",
  },
  { title: "Key files", hint: "The paths that matter, one line each." },
  { title: "Gotchas", hint: "What is not obvious from the code." },
];

export const BRIEFING_TEMPLATE = BRIEFING_SECTIONS.map(
  (section) => `## ${section.title}\n`,
).join("\n");

export function sectionHeadings(markdown: string): string[] {
  return [...markdown.matchAll(/^##\s+(.+?)\s*$/gm)].map((m) => m[1]);
}

export function missingSections(markdown: string): BriefingSection[] {
  const present = new Set(
    sectionHeadings(markdown).map((heading) => heading.toLowerCase()),
  );
  return BRIEFING_SECTIONS.filter(
    (section) => !present.has(section.title.toLowerCase()),
  );
}

export function appendSection(markdown: string, heading: string): string {
  const base = markdown.replace(/\s+$/, "");
  return `${base}${base ? "\n\n" : ""}## ${heading}\n\n`;
}

/** A stable anchor for a heading, so the outline can scroll to it. */
export function headingAnchor(heading: string): string {
  return heading
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}
