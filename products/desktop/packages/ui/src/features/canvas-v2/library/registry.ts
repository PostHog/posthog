import barChartCode from "./templates/bar-chart.tsx.txt?raw";
import checklistCode from "./templates/checklist.tsx.txt?raw";
import dateRangeCode from "./templates/date-range.tsx.txt?raw";
import headingCode from "./templates/heading.tsx.txt?raw";
import insightCode from "./templates/insight.tsx.txt?raw";
import kpiCode from "./templates/kpi.tsx.txt?raw";
import notesCode from "./templates/notes.tsx.txt?raw";
import sqlTableCode from "./templates/sql-table.tsx.txt?raw";
import stickyCode from "./templates/sticky.tsx.txt?raw";
import trendChartCode from "./templates/trend-chart.tsx.txt?raw";

export interface CanvasV2LibraryEntry {
  /** Slug, and the prefix of the default fragment id. */
  name: string;
  label: string;
  /** One sentence, read by people in the palette and by the agent in its prompt. */
  description: string;
  /** A lucide-react icon name. */
  icon: string;
  defaultSize: { w: number; h: number };
  /** The full TSX source of the fragment. */
  code: string;
}

export const CANVAS_V2_LIBRARY: readonly CanvasV2LibraryEntry[] = [
  {
    name: "sticky",
    label: "Sticky note",
    description:
      "An editable note that all collaborators share. The text is kept in shared state under the key sticky:note.",
    icon: "StickyNote",
    defaultSize: { w: 260, h: 200 },
    code: stickyCode,
  },
  {
    name: "heading",
    label: "Heading",
    description:
      "One large heading with an optional second line, to give a group of fragments a name.",
    icon: "Heading",
    defaultSize: { w: 480, h: 160 },
    code: headingCode,
  },
  {
    name: "date-range",
    label: "Date range",
    description:
      "A select of date presets that writes the shared dateRange key. Every data fragment reads that key.",
    icon: "CalendarRange",
    defaultSize: { w: 320, h: 160 },
    code: dateRangeCode,
  },
  {
    name: "kpi",
    label: "Single number",
    description:
      "One number counted with HogQL over the shared dateRange, with a label above it.",
    icon: "Gauge",
    defaultSize: { w: 300, h: 180 },
    code: kpiCode,
  },
  {
    name: "trend-chart",
    label: "Trend chart",
    description:
      "A line chart of one event per day over the shared dateRange, drawn with Recharts.",
    icon: "ChartLine",
    defaultSize: { w: 560, h: 320 },
    code: trendChartCode,
  },
  {
    name: "bar-chart",
    label: "Bar chart",
    description:
      "A bar chart of the top pages over the shared dateRange, from a HogQL group by.",
    icon: "ChartColumn",
    defaultSize: { w: 560, h: 320 },
    code: barChartCode,
  },
  {
    name: "insight",
    label: "Saved insight",
    description:
      "A saved PostHog insight loaded by its short id, re-scoped to the shared dateRange. The short id is kept in shared state.",
    icon: "Lightbulb",
    defaultSize: { w: 420, h: 260 },
    code: insightCode,
  },
  {
    name: "sql-table",
    label: "HogQL table",
    description:
      "A HogQL query box and its result table. The text {since} in the query becomes the start of the shared dateRange.",
    icon: "Table",
    defaultSize: { w: 720, h: 420 },
    code: sqlTableCode,
  },
  {
    name: "checklist",
    label: "Checklist",
    description:
      "A shared list of items with checkboxes. The items are kept in shared state under the key checklist:items.",
    icon: "ListChecks",
    defaultSize: { w: 380, h: 320 },
    code: checklistCode,
  },
  {
    name: "notes",
    label: "Markdown notes",
    description:
      "Markdown text that all collaborators share, with an edit button. The text is kept in shared state under the key notes:text.",
    icon: "NotebookPen",
    defaultSize: { w: 420, h: 320 },
    code: notesCode,
  },
];

export function libraryEntry(name: string): CanvasV2LibraryEntry | undefined {
  return CANVAS_V2_LIBRARY.find((entry) => entry.name === name);
}
