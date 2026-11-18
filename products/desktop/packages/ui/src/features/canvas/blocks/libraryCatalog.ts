import {
  ArrowClockwise,
  ArrowsLeftRight,
  CalendarBlank,
  ChartBar,
  ChartLine,
  Clock,
  Code,
  Cube,
  FadersHorizontal,
  Funnel,
  GridFour,
  type Icon,
  Info,
  ListNumbers,
  Minus,
  NumberSquareOne,
  Paragraph,
  Pulse,
  SlidersHorizontal,
  Target,
  TextH,
} from "@phosphor-icons/react";
import {
  BLOCK_DEFINITIONS,
  type BlockDefinition,
  type BlockGroup,
  blockDefinition,
} from "@posthog/core/canvas/blockLibrary/blockDefinitions";
import { componentLabel } from "@posthog/core/canvas/blockLibrary/params";

const ICONS: Record<string, Icon> = {
  Metric: NumberSquareOne,
  Trend: ChartLine,
  TopList: ListNumbers,
  Funnel,
  SqlTable: Code,
  DateRange: CalendarBlank,
  Interval: Clock,
  PropertyFilter: SlidersHorizontal,
  Filters: FadersHorizontal,
  Goal: Target,
  RecentEvents: Pulse,
  Callout: Info,
  Insight: ChartBar,
  Retention: GridFour,
  Compare: ArrowsLeftRight,
  Refresh: ArrowClockwise,
  Heading: TextH,
  Paragraph,
  Divider: Minus,
};

export const LIBRARY_GROUPS: BlockGroup[] = ["Data", "Controls", "Content"];

export interface LibraryEntry extends BlockDefinition {
  icon: Icon;
}

export const LIBRARY: LibraryEntry[] = BLOCK_DEFINITIONS.map((definition) => ({
  ...definition,
  icon: ICONS[definition.type] ?? Cube,
}));

const ELEMENT_LABELS: Record<string, string> = {
  h1: "Heading",
  h2: "Heading",
  h3: "Heading",
  p: "Text",
  hr: "Divider",
  header: "Header",
  main: "Page",
  section: "Section",
};

export const EDIT_LABELS: Record<string, string> = {
  ...ELEMENT_LABELS,
  ...Object.fromEntries(
    BLOCK_DEFINITIONS.map((definition) => [definition.type, definition.label]),
  ),
};

export function libraryLabel(blockType: string | null, tag?: string): string {
  if (blockType) {
    return blockDefinition(blockType)?.label ?? componentLabel(blockType);
  }
  return (tag && ELEMENT_LABELS[tag]) || "Element";
}

export function libraryIcon(blockType: string | null): Icon {
  return (blockType && ICONS[blockType]) || Cube;
}
