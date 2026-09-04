import barChartCode from "./templates/bar-chart.tsx.txt?raw";
import checklistCode from "./templates/checklist.tsx.txt?raw";
import dateFrameCode from "./templates/date-frame.tsx.txt?raw";
import dateRangeCode from "./templates/date-range.tsx.txt?raw";
import headingCode from "./templates/heading.tsx.txt?raw";
import insightCode from "./templates/insight.tsx.txt?raw";
import kpiCode from "./templates/kpi.tsx.txt?raw";
import layoutCode from "./templates/layout.tsx.txt?raw";
import notesCode from "./templates/notes.tsx.txt?raw";
import slideshowCode from "./templates/slideshow.tsx.txt?raw";
import sqlTableCode from "./templates/sql-table.tsx.txt?raw";
import stickyCode from "./templates/sticky.tsx.txt?raw";
import textCode from "./templates/text.tsx.txt?raw";
import trendChartCode from "./templates/trend-chart.tsx.txt?raw";

/**
 * The three parts of the palette: things you write, things that query, and
 * frames that hold the other fragments and place them.
 */
export type CanvasV2LibraryGroup = "notes" | "data" | "frames";

export interface CanvasV2LibraryEntry {
  /** Slug, and the prefix of the default fragment id. */
  name: string;
  label: string;
  /** One sentence, read by people in the palette and by the agent in its prompt. */
  description: string;
  group: CanvasV2LibraryGroup;
  /** A lucide-react icon name. */
  icon: string;
  defaultSize: { w: number; h: number };
  surface?: "card" | "plain";
  /** A frame goes behind the fragments, so what sits on it stays clickable. */
  layer?: "back";
  /** The full TSX source of the fragment. */
  code: string;
}

export const CANVAS_V2_LIBRARY: readonly CanvasV2LibraryEntry[] = [
  {
    name: "sticky",
    label: "Sticky note",
    description:
      "An editable note that all collaborators share, in one of four colors.",
    group: "notes",
    icon: "StickyNote",
    defaultSize: { w: 260, h: 220 },
    surface: "plain",
    code: stickyCode,
  },
  {
    name: "text",
    label: "Text",
    description:
      "Shared text with nothing drawn behind it, to write over or beside other fragments.",
    group: "notes",
    icon: "Type",
    defaultSize: { w: 360, h: 120 },
    surface: "plain",
    code: textCode,
  },
  {
    name: "heading",
    label: "Heading",
    description:
      "One large heading with an optional second line, to give a group of fragments a name.",
    group: "notes",
    icon: "Heading",
    defaultSize: { w: 480, h: 120 },
    surface: "plain",
    code: headingCode,
  },
  {
    name: "notes",
    label: "Markdown notes",
    description:
      "Markdown text that everyone shares, with an edit button to change it.",
    group: "notes",
    icon: "NotebookPen",
    defaultSize: { w: 420, h: 320 },
    code: notesCode,
  },
  {
    name: "checklist",
    label: "Checklist",
    description:
      "A shared list of items with checkboxes, and a title you can rename.",
    group: "notes",
    icon: "ListChecks",
    defaultSize: { w: 380, h: 320 },
    code: checklistCode,
  },
  {
    name: "date-range",
    label: "Date range",
    description:
      "The date range every data fragment on the board follows. Add one of these first.",
    group: "data",
    icon: "CalendarRange",
    defaultSize: { w: 300, h: 76 },
    surface: "plain",
    code: dateRangeCode,
  },
  {
    name: "kpi",
    label: "Single number",
    description:
      "One number for an event you pick, with the change against the range before it.",
    group: "data",
    icon: "Gauge",
    defaultSize: { w: 300, h: 180 },
    code: kpiCode,
  },
  {
    name: "trend-chart",
    label: "Trend chart",
    description:
      "A line of one event by day or by week, for an event you pick.",
    group: "data",
    icon: "ChartLine",
    defaultSize: { w: 560, h: 320 },
    code: trendChartCode,
  },
  {
    name: "bar-chart",
    label: "Bar chart",
    description:
      "The top values of a property you pick, such as the page path or the browser.",
    group: "data",
    icon: "ChartColumn",
    defaultSize: { w: 560, h: 320 },
    code: barChartCode,
  },
  {
    name: "insight",
    label: "Saved insight",
    description:
      "A saved PostHog insight, drawn from its short id and re-scoped to the board date range.",
    group: "data",
    icon: "Lightbulb",
    defaultSize: { w: 420, h: 260 },
    code: insightCode,
  },
  {
    name: "sql-table",
    label: "HogQL table",
    description:
      "A HogQL query and its result table. The query is shared and stays after a reload.",
    group: "data",
    icon: "Table",
    defaultSize: { w: 720, h: 420 },
    code: sqlTableCode,
  },
  {
    name: "layout",
    label: "Layout frame",
    description:
      "Drag fragments onto this frame and it puts them in a grid, and keeps them together.",
    group: "frames",
    icon: "LayoutGrid",
    defaultSize: { w: 800, h: 520 },
    surface: "plain",
    layer: "back",
    code: layoutCode,
  },
  {
    name: "date-frame",
    label: "Date frame",
    description:
      "Every data fragment on this frame follows the date range of the frame, not the board.",
    group: "frames",
    icon: "CalendarRange",
    defaultSize: { w: 800, h: 420 },
    surface: "plain",
    layer: "back",
    code: dateFrameCode,
  },
  {
    name: "slideshow",
    label: "Slideshow",
    description:
      "A slide for every fragment you drop on this frame. Full page it becomes a presentation.",
    group: "frames",
    icon: "Presentation",
    defaultSize: { w: 800, h: 520 },
    surface: "plain",
    layer: "back",
    code: slideshowCode,
  },
];

export function libraryEntry(name: string): CanvasV2LibraryEntry | undefined {
  return CANVAS_V2_LIBRARY.find((entry) => entry.name === name);
}
