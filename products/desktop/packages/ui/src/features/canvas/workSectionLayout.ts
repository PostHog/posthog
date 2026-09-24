export type WorkSectionId = "pinned" | "recent" | "spaces";

export type WorkSectionHeights = Record<WorkSectionId, number>;

export type PreferredWorkSectionHeights = Partial<
  Record<WorkSectionId, number>
>;

export interface WorkSectionInput {
  id: WorkSectionId;
  open: boolean;
  contentHeight: number;
}

export const WORK_SECTION_FILL_ORDER: readonly WorkSectionId[] = [
  "recent",
  "spaces",
  "pinned",
];

export const WORK_SECTION_HEADER_HEIGHT = 28;
export const WORK_SECTION_SHARE_CAP = 0.4;
export const WORK_SECTION_MIN_HEIGHT = 56;
export const WORK_SECTION_MIN_DRAG_HEIGHT = 40;

const EMPTY_HEIGHTS: WorkSectionHeights = { pinned: 0, recent: 0, spaces: 0 };

export function fillingWorkSection(
  sections: readonly WorkSectionInput[],
): WorkSectionId | null {
  return (
    WORK_SECTION_FILL_ORDER.find((id) =>
      sections.some((section) => section.id === id && section.open),
    ) ?? null
  );
}

export function layoutWorkSections(
  sections: readonly WorkSectionInput[],
  available: number,
  preferred: PreferredWorkSectionHeights = {},
): WorkSectionHeights {
  const heights = { ...EMPTY_HEIGHTS };
  const fill = fillingWorkSection(sections);
  if (fill === null || available <= 0) return heights;

  const open = sections.filter((section) => section.open);
  const fillSection = open.find((section) => section.id === fill);
  if (!fillSection) return heights;
  const others = open.filter((section) => section.id !== fill);
  const share = Math.round(available * WORK_SECTION_SHARE_CAP);

  let used = 0;
  for (const section of others) {
    const wanted = preferred[section.id] ?? share;
    heights[section.id] = Math.floor(
      Math.max(0, Math.min(section.contentHeight, wanted)),
    );
    used += heights[section.id];
  }

  const fillFloor = Math.min(
    fillSection.contentHeight,
    WORK_SECTION_MIN_HEIGHT,
  );
  if (available - used < fillFloor && used > 0) {
    const scale = Math.max(0, available - fillFloor) / used;
    used = 0;
    for (const section of others) {
      heights[section.id] = Math.floor(heights[section.id] * scale);
      used += heights[section.id];
    }
  }

  heights[fill] = Math.floor(
    Math.min(fillSection.contentHeight, Math.max(0, available - used)),
  );

  let leftover = available - used - heights[fill];
  for (const id of WORK_SECTION_FILL_ORDER) {
    if (leftover <= 0) break;
    const section = others.find((candidate) => candidate.id === id);
    if (!section || preferred[id] !== undefined) continue;
    const grow = Math.min(leftover, section.contentHeight - heights[id]);
    if (grow <= 0) continue;
    heights[id] += Math.floor(grow);
    leftover -= Math.floor(grow);
  }

  return heights;
}

export function resizeWorkSections({
  sections,
  heights,
  upper,
  lower,
  delta,
  preferred,
}: {
  sections: readonly WorkSectionInput[];
  heights: WorkSectionHeights;
  upper: WorkSectionId;
  lower: WorkSectionId;
  delta: number;
  preferred: PreferredWorkSectionHeights;
}): PreferredWorkSectionHeights {
  const contentOf = (id: WorkSectionId): number =>
    sections.find((section) => section.id === id)?.contentHeight ?? 0;
  const shrinkable = (id: WorkSectionId): number =>
    Math.max(0, heights[id] - WORK_SECTION_MIN_DRAG_HEIGHT);
  const growable = (id: WorkSectionId): number =>
    Math.max(0, contentOf(id) - heights[id]);
  const min = -Math.min(shrinkable(upper), growable(lower));
  const max = Math.min(growable(upper), shrinkable(lower));
  const applied = Math.max(min, Math.min(max, delta));
  const fill = fillingWorkSection(sections);
  const next = { ...preferred };
  if (upper !== fill) next[upper] = heights[upper] + applied;
  if (lower !== fill) next[lower] = heights[lower] - applied;
  return next;
}
