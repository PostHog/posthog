import { freeformSystemPromptFor } from "@posthog/core/canvas/canvasTemplates";
import { FREEFORM_STARTER_CODE } from "@posthog/core/canvas/freeformStarter";

// Builds the prompt for the task that generates a freeform (React) canvas. Like
// CONTEXT.md generation, this runs as a normal repo-less agent task (no repo
// picked up front), so the agent has the default system prompt — the freeform
// authoring contract
// (imports, the `ph` data shim, Quill/style rules) therefore has to live in the
// task's content (its first user message). The canvas is not a file on disk — it
// lives in PostHog — so the agent publishes the result via the PostHog MCP tool
// `desktop-file-system-canvas-partial-update` rather than replying with code or
// writing a file.
export function buildFreeformGenerationPrompt(input: {
  dashboardId: string;
  name: string;
  channelName: string;
  templateId?: string;
  instruction: string;
  // The current source, when editing an existing canvas. Omitted for a first build.
  currentCode?: string;
  // Default on (opt out via the generate bar): seed a known-good starter
  // scaffold as the agent's baseline on a FIRST build, so it edits a compiling
  // app instead of authoring boilerplate from scratch. Ignored when editing.
  useStarter?: boolean;
}): string {
  const {
    dashboardId,
    name,
    channelName,
    templateId,
    instruction,
    currentCode,
    useStarter,
  } = input;

  const contract = freeformSystemPromptFor(templateId);
  const isEdit = !!currentCode?.trim();

  // The header points back to the user's request, which leads the message
  // (outside this block). Without that pointer the agent can read the header as
  // a self-contained task and under-weight the actual instruction above.
  const header = isEdit
    ? `Edit the freeform React canvas "${name}" in the channel "${channelName}", per the user's request at the start of this message.`
    : `Build a freeform React canvas "${name}" for the channel "${channelName}", per the user's request at the start of this message.`;

  const currentBlock = isEdit
    ? `\n[Current code] — the canvas as it stands now. Rewrite the WHOLE file with the change applied; do not output a partial file.\n\n\`\`\`tsx\n${currentCode}\n\`\`\`\n`
    : "";

  // First-build only: hand the agent a working scaffold to build ON instead of
  // authoring from zero. It already wires the easy-to-get-wrong bits (date
  // picker, theme tokens, loading skeletons, typed-node result reading).
  const starterBlock =
    !isEdit && useStarter
      ? `\n[Starter scaffold] — begin from this WORKING baseline instead of authoring from scratch. It already wires the things that are easy to get wrong: the date picker, theme-aware tokens, per-card loading skeletons, and reading a typed-node result correctly. KEEP that wiring; replace the sample "total events" metric and the layout with what the user asked for, and output the COMPLETE rewritten file.\n\n\`\`\`tsx\n${FREEFORM_STARTER_CODE}\n\`\`\`\n`
      : "";

  // The standing authoring contract + publishing/data rules are the same
  // boilerplate on every canvas generation — the user never typed them. Wrap
  // them in a `<canvas_generation_instructions>` element so the conversation UI
  // collapses them into a single clickable tag instead of dumping the full body
  // inline (see extractCanvasInstructions). Kept after the user's instruction so
  // the request leads, mirroring how channel CONTEXT.md is appended.
  const instructions = `${header}
${currentBlock}${starterBlock}
Follow this authoring contract for the canvas (imports, the \`ph\` data shim, and
style rules):

${contract}

PUBLISHING — this OVERRIDES any instruction above about replying with the code in
a fenced \`\`\`tsx block. In this task you do NOT reply with the code. When the
canvas is ready, PUBLISH it by calling the PostHog MCP tool
\`desktop-file-system-canvas-partial-update\` exactly once with:
- id: "${dashboardId}"
- code: the COMPLETE single-file React source for the canvas.

The canvas lives in PostHog, not on disk — calling that MCP tool is what saves it.
Do not write a local file. Verify event/property names via the PostHog MCP before
using them, and operate only on this project.

DATA — for each metric, first SAVE an insight via the PostHog MCP insight tools
(prefer an insight query type — Trends, Funnels, Retention, web-analytics kinds —
over raw SQL), record the \`short_id\` it returns, and load it in the canvas with
\`ph.loadInsight(short_id, { dateRange })\`. Fall back to inline \`ph.query(...)\`/HogQL
only when no insight can express the metric.`;

  return `${instruction}

<canvas_generation_instructions>
${instructions}
</canvas_generation_instructions>`;
}
