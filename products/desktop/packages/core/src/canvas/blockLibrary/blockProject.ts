import { CANVAS_PLATFORM_MANIFEST } from "@posthog/shared";
import type { CanvasSourceProject } from "../dashboardSchemas";
import {
  BLOCK_ICONS_PATH,
  BLOCK_RUNTIME_PATH,
  componentPath,
} from "./blockDefinitions";
import { withLibraryFile } from "./blockLibrarySync";
import { BLOCK_COMPONENT_SOURCES } from "./componentSources";

export const CANVAS_ENTRY_PATH = "src/canvas.tsx";

const ENTRY_HTML = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/canvas.tsx"></script>
  </body>
</html>
`;

const BLANK_CANVAS = `import { DateRange } from "./blocks/DateRange";

export default function Canvas() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Untitled canvas</h1>
          <p className="text-sm text-muted-foreground">What this canvas shows, in one sentence.</p>
        </div>
        <DateRange blockId="b-range" />
      </header>
    </main>
  );
}
`;

const PRODUCT_OVERVIEW_CANVAS = `import { DateRange } from "./blocks/DateRange";
import { Interval } from "./blocks/Interval";
import { Metric } from "./blocks/Metric";
import { PropertyFilter } from "./blocks/PropertyFilter";
import { TopList } from "./blocks/TopList";
import { Trend } from "./blocks/Trend";

export default function Canvas() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Product overview</h1>
          <p className="text-sm text-muted-foreground">How many people use the product, and what they do.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PropertyFilter blockId="b-browser" property="$browser" label="Browser" />
          <Interval blockId="b-interval" />
          <DateRange blockId="b-range" />
        </div>
      </header>
      <div className="grid gap-4 sm:grid-cols-3">
        <Metric blockId="b-wau" title="Weekly active users" event="$pageview" math="weekly_active" />
        <Metric blockId="b-dau" title="Daily active users" event="$pageview" math="dau" />
        <Metric blockId="b-views" title="Pageviews" event="$pageview" math="total" />
      </div>
      <Trend blockId="b-trend" title="Active users over time" events={["$pageview"]} math="dau" display="area" />
      <div className="grid gap-4 sm:grid-cols-2">
        <TopList blockId="b-pages" title="Top pages" event="$pageview" breakdown="$pathname" limit={8} />
        <TopList blockId="b-browsers" title="Browsers" event="$pageview" breakdown="$browser" limit={8} />
      </div>
    </main>
  );
}
`;

export interface CanvasStarter {
  id: string;
  name: string;
  description: string;
  source: string;
}

export const CANVAS_STARTERS: CanvasStarter[] = [
  {
    id: "blank",
    name: "Blank",
    description: "A title and a date range, then add blocks from the panel",
    source: BLANK_CANVAS,
  },
  {
    id: "product-overview",
    name: "Product overview",
    description: "Active users, pageviews, top pages and browsers",
    source: PRODUCT_OVERVIEW_CANVAS,
  },
];

function platformDependencies(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(CANVAS_PLATFORM_MANIFEST.dependencies).map(
      ([name, entry]) => [name, entry.version],
    ),
  );
}

function usedComponents(source: string): string[] {
  const used: string[] = [];
  for (const match of source.matchAll(
    /from\s+["']\.\/blocks\/([A-Za-z]+)["']/g,
  )) {
    const name = match[1];
    if (name && BLOCK_COMPONENT_SOURCES[name]) used.push(name);
  }
  return used;
}

interface Capabilities {
  posthog?: {
    insights?: string[];
    inlineQueries?: boolean;
    captureEvents?: string[];
    state?: string[];
    actions?: string[];
    agentRequests?: boolean;
  };
  network?: { origins?: string[] };
  connectors?: unknown[];
}

export function completeCapabilities(
  capabilities: unknown,
): Capabilities | undefined {
  if (!capabilities || typeof capabilities !== "object") return undefined;
  const current = capabilities as Capabilities;
  if (!current.posthog) return current;
  return {
    ...current,
    posthog: {
      insights: [],
      captureEvents: [],
      actions: [],
      agentRequests: false,
      ...current.posthog,
    },
  };
}

const INSIGHT_BLOCK_ID = /<Insight\b[^>]*?\bshortId="([^"]+)"/g;

function insightBlockIds(files: Record<string, string>): string[] {
  return Object.values(files).flatMap((source) =>
    Array.from(source.matchAll(INSIGHT_BLOCK_ID), (match) => match[1]),
  );
}

export function withBlockCapabilities(
  capabilities: unknown,
  files: Record<string, string> = {},
): Capabilities {
  const current = (capabilities ?? {}) as Capabilities;
  const posthog = current.posthog ?? {};
  const state = new Set(posthog.state ?? []);
  state.add("user");
  const insights = new Set([
    ...(posthog.insights ?? []),
    ...insightBlockIds(files),
  ]);
  return {
    ...current,
    posthog: {
      captureEvents: posthog.captureEvents ?? [],
      actions: posthog.actions ?? [],
      agentRequests: posthog.agentRequests ?? false,
      ...posthog,
      insights: Array.from(insights),
      inlineQueries: true,
      state: Array.from(state),
    },
    network: current.network ?? { origins: [] },
  };
}

export function starterProject(starter: CanvasStarter): CanvasSourceProject {
  let files: Record<string, string> = withLibraryFile(
    { "index.html": ENTRY_HTML, [CANVAS_ENTRY_PATH]: starter.source },
    BLOCK_RUNTIME_PATH,
  );
  files = withLibraryFile(files, BLOCK_ICONS_PATH);
  for (const component of usedComponents(starter.source)) {
    files = withLibraryFile(files, componentPath(component));
  }
  return {
    schemaVersion: 1,
    entryHtml: "index.html",
    files,
    dependencies: platformDependencies(),
    canvasSdkVersion: CANVAS_PLATFORM_MANIFEST.canvasSdkVersion,
    capabilities: withBlockCapabilities(undefined),
  };
}

export function usesBlocks(files: Record<string, string>): boolean {
  return BLOCK_RUNTIME_PATH in files;
}
