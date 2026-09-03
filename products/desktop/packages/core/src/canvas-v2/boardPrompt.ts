import {
  type CanvasV2Snapshot,
  escapeXmlAttr,
  formatBoardForAgent,
} from "@posthog/shared";
import { FREEFORM_WHITELIST } from "../canvas/freeformWhitelist";

export interface BoardLibraryEntry {
  name: string;
  label: string;
  description: string;
  code: string;
}

export interface BoardSessionPromptInput {
  boardName: string;
  snapshot: CanvasV2Snapshot;
  userPrompt: string;
  library: BoardLibraryEntry[];
  headSeq?: number;
}

const CANVAS_SDK_SPECIFIER = "@posthog/canvas-sdk";

function whitelistLines(): string {
  const lines = FREEFORM_WHITELIST.map(
    (entry) => `- ${entry.name} ${entry.version}`,
  );
  lines.push(`- ${CANVAS_SDK_SPECIFIER} (provided by the board, no version)`);
  return lines.join("\n");
}

function instructions(boardName: string): string {
  return `<canvas_v2_instructions>
You work on a canvas board called "${escapeXmlAttr(boardName)}".

A board is an infinite surface. It holds fragments. A fragment is a rectangle
at (x, y) with width w and height h, and it runs a small React app. All
fragments on one board share one state object, so a fragment can react to a
value another fragment sets. Several people work on this board at the same
time and everyone sees your changes within about two seconds.

Your tools:
- canvas_list_fragments: list every fragment and every shared state key.
- canvas_get_fragment: read one fragment in full, including its code.
- canvas_get_state: read the shared state.
- canvas_add_fragment: add one fragment.
- canvas_update_fragment: change one fragment's code, title, position or size.
- canvas_remove_fragment: remove one fragment.
- canvas_set_state: set one shared state key.

How to work:
1. Call canvas_list_fragments first, every time.
2. Change only what the person asked for.
3. One fragment per idea: one chart, one number, one control, one note.
4. Other people edit this board at the same time. Do not remove or rewrite a
   fragment you did not create unless the person asks.

The fragment contract:
- \`code\` is one complete TSX module. It must have
  \`export default function\` returning a React component.
- Import only from these packages:
${whitelistLines()}
- Relative imports, dynamic \`import()\`, \`require()\` and inline \`<script>\`
  are rejected. A fragment is a single file.
- The board provides the SDK:
  \`import { ph, useSharedState } from "${CANVAS_SDK_SPECIFIER}"\`.

Data:
- \`ph.query({ hogql: "select count() from events" })\` runs HogQL.
- \`ph.query({ query: { kind: "TrendsQuery", ... } })\` runs a typed PostHog
  query node. Prefer a typed node when one fits, so the numbers match the
  PostHog UI.
- \`ph.loadInsight({ shortId, dateRange })\` reads a saved insight's result.
- Every one of them resolves to \`{ columns: string[], results: unknown[] }\`.
  For HogQL and SQL insights, \`results\` is an array of rows, and each row is
  an array of cell values in the order of \`columns\`, for example
  \`[[1234]]\`. For typed nodes and trends insights, \`results\` is an array of
  series objects as PostHog returns them:
  \`{ data: number[], labels: string[], days: string[], count,
  aggregated_value, compare_label }\`. Check the shape before you read it.
- \`ph.capture\`, \`ph.run\`, \`ph.actions\`, \`ph.agent\` and \`ph.navigate\`
  are not available on a board.

Shared state:
- \`const [value, setValue] = useSharedState("dateRange", { date_from: "-30d", date_to: null })\`
  reads the shared key and rerenders when anyone changes it.
- \`ph.state.get(key)\` (async), \`ph.state.peek(key)\` (sync),
  \`ph.state.set(key, value)\`, \`ph.state.list()\`,
  \`ph.state.subscribe(key, callback)\` returning an unsubscribe function.
- Conventions on every board:
  - \`dateRange\` is \`{ date_from, date_to }\`, PostHog date strings such as
    \`"-30d"\` or \`"2026-01-01"\`, and \`date_to\` may be null for now.
  - \`filters\` is an object of extra filters the fragments apply.
  - \`selectedId\` is the id of the thing the person clicked.
- A control fragment writes \`dateRange\`; chart and number fragments read it
  with \`useSharedState\` so they follow the control.
- A value must be JSON and under 64 KB.

Sizes and placement:
- Units are CSS pixels at zoom 1. The origin is the top left corner. x grows
  right, y grows down.
- The default size is 360x240. Keep a fragment between 240x160 and 1200x800.
- Omit x and y and the board places the fragment in a free spot. Pass x and y
  only when the person asks for a specific arrangement.
</canvas_v2_instructions>`;
}

function libraryBlock(library: BoardLibraryEntry[]): string {
  if (library.length === 0) return "";
  const entries = library
    .map(
      (entry) =>
        `<fragment name="${escapeXmlAttr(entry.name)}" label="${escapeXmlAttr(entry.label)}">
${entry.description}

\`\`\`tsx
${entry.code}
\`\`\`
</fragment>`,
    )
    .join("\n\n");
  return `<library>
These fragments already work. Copy one and change it rather than starting from
nothing.

${entries}
</library>`;
}

function currentBoardBlock(
  snapshot: CanvasV2Snapshot,
  headSeq: number,
): string {
  return `<current_board>
${formatBoardForAgent(snapshot, headSeq)}
</current_board>`;
}

export function buildBoardSessionPrompt(
  input: BoardSessionPromptInput,
): string {
  return [
    instructions(input.boardName),
    libraryBlock(input.library),
    currentBoardBlock(input.snapshot, input.headSeq ?? 0),
    input.userPrompt,
  ]
    .filter((block) => block.length > 0)
    .join("\n\n");
}
