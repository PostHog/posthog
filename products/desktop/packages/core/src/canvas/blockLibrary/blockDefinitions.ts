export type BlockGroup = "Data" | "Controls" | "Content";

export type BlockPropValue = string | number | boolean | string[] | undefined;
export type BlockPropsRecord = Record<string, BlockPropValue>;

export interface BlockDefinition {
  type: string;
  label: string;
  description: string;
  group: BlockGroup;
  component?: string;
  presets?: BlockPropsRecord[];
  element?: string;
  needsSetup?: boolean;
}

export const BLOCKS_DIR = "src/blocks";
export const BLOCK_RUNTIME_PATH = `${BLOCKS_DIR}/runtime.tsx`;
export const BLOCK_ICONS_PATH = `${BLOCKS_DIR}/icons.tsx`;

const DEFINITIONS: Omit<BlockDefinition, "component">[] = [
  {
    type: "Metric",
    label: "Number",
    description: "One big number with the change from the previous period",
    group: "Data",
    presets: [
      { title: "Pageviews", event: "$pageview", math: "total" },
      { title: "Daily active users", event: "$pageview", math: "dau" },
      {
        title: "Weekly active users",
        event: "$pageview",
        math: "weekly_active",
      },
      {
        title: "Monthly active users",
        event: "$pageview",
        math: "monthly_active",
      },
      { title: "Autocaptured events", event: "$autocapture", math: "total" },
    ],
  },
  {
    type: "Trend",
    label: "Trend",
    description: "Events over time as a line, bar or area chart",
    group: "Data",
    presets: [
      { title: "Pageviews over time", events: ["$pageview"], display: "line" },
      {
        title: "Active users over time",
        events: ["$pageview"],
        math: "dau",
        display: "area",
      },
      {
        title: "Pageviews by browser",
        events: ["$pageview"],
        breakdown: "$browser",
        display: "bar",
      },
    ],
  },
  {
    type: "TopList",
    label: "Top list",
    description: "The top values of a property, ranked by count",
    group: "Data",
    presets: [
      {
        title: "Top pages",
        event: "$pageview",
        breakdown: "$pathname",
        limit: 8,
      },
      {
        title: "Browsers",
        event: "$pageview",
        breakdown: "$browser",
        limit: 8,
      },
      {
        title: "Referring domains",
        event: "$pageview",
        breakdown: "$referring_domain",
        limit: 8,
      },
      {
        title: "Countries",
        event: "$pageview",
        breakdown: "$geoip_country_name",
        limit: 8,
      },
      {
        title: "Devices",
        event: "$pageview",
        breakdown: "$device_type",
        limit: 8,
      },
    ],
  },
  {
    type: "Funnel",
    label: "Funnel",
    description: "Conversion through a series of steps",
    group: "Data",
    presets: [
      {
        title: "Conversion",
        steps: ["$pageview", "$autocapture"],
        windowDays: 14,
      },
    ],
  },
  {
    type: "SqlTable",
    label: "SQL",
    description: "Any HogQL query as a table",
    group: "Data",
    presets: [
      {
        title: "Top events",
        query:
          "SELECT event, count() AS total FROM events WHERE {filters} GROUP BY event ORDER BY total DESC LIMIT 10",
      },
    ],
  },
  {
    type: "Goal",
    label: "Goal",
    description: "A number against a target, with progress",
    group: "Data",
    presets: [
      { title: "Pageviews goal", event: "$pageview", target: 50000 },
      {
        title: "Active users goal",
        event: "$pageview",
        math: "dau",
        target: 100,
      },
    ],
  },
  {
    type: "Insight",
    label: "Saved insight",
    description: "Any saved insight from PostHog, kept in sync",
    group: "Data",
    presets: [{ span: "wide" }],
    needsSetup: true,
  },
  {
    type: "Retention",
    label: "Retention",
    description: "How many people come back, period by period",
    group: "Data",
    presets: [
      {
        title: "Weekly retention",
        startEvent: "$pageview",
        returnEvent: "$pageview",
        period: "Week",
        intervals: 8,
        span: "wide",
      },
    ],
  },
  {
    type: "RecentEvents",
    label: "Recent events",
    description: "A live feed of the latest events",
    group: "Data",
    presets: [{ title: "Recent events", limit: 12 }],
  },
  {
    type: "DateRange",
    label: "Date range",
    description: "Sets the time range for every block on the canvas",
    group: "Controls",
  },
  {
    type: "Interval",
    label: "Interval",
    description: "Group charts by day, week or month",
    group: "Controls",
  },
  {
    type: "Filters",
    label: "Filters",
    description: "Let viewers filter every block by any property",
    group: "Controls",
  },
  {
    type: "PropertyFilter",
    label: "Quick filter",
    description: "A dropdown for the values of one property",
    group: "Controls",
    presets: [{ property: "$browser", label: "Browser" }],
  },
  {
    type: "Compare",
    label: "Compare",
    description: "Draw the previous period on every trend chart",
    group: "Controls",
  },
  {
    type: "Refresh",
    label: "Refresh",
    description: "Reload every block and show when data last loaded",
    group: "Controls",
  },
  {
    type: "Heading",
    label: "Heading",
    description: "A section title",
    group: "Content",
    element:
      '<h2 className="text-lg font-semibold tracking-tight">Section title</h2>',
  },
  {
    type: "Paragraph",
    label: "Text",
    description: "A short note or explanation",
    group: "Content",
    element:
      '<p className="text-sm text-muted-foreground">Write a note about what this shows.</p>',
  },
  {
    type: "Divider",
    label: "Divider",
    description: "A line between parts of the canvas",
    group: "Content",
    element: '<hr className="border-border" />',
  },
  {
    type: "Callout",
    label: "Callout",
    description: "A highlighted note or warning",
    group: "Content",
    presets: [
      {
        tone: "info",
        title: "Worth knowing",
        text: "Add a short note for the people who read this canvas.",
      },
    ],
  },
];

export const BLOCK_DEFINITIONS: BlockDefinition[] = DEFINITIONS.map(
  (definition) =>
    definition.element
      ? definition
      : { ...definition, component: definition.type },
);

const BY_TYPE = new Map(
  BLOCK_DEFINITIONS.map((definition) => [definition.type, definition]),
);

export function blockDefinition(type: string): BlockDefinition | undefined {
  return BY_TYPE.get(type);
}

export function componentPath(component: string): string {
  return `${BLOCKS_DIR}/${component}.tsx`;
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function freshBlockProps(
  definition: BlockDefinition,
  files: Record<string, string>,
): BlockPropsRecord {
  const presets = definition.presets ?? [{}];
  const source = Object.values(files).join("\n");
  const used = (preset: BlockPropsRecord) =>
    new RegExp(
      `<${definition.component}\\b[^>]*\\btitle="${escapeRegExp(String(preset.title ?? ""))}"`,
    ).test(source);
  return presets.find((preset) => !used(preset)) ?? presets[0];
}
