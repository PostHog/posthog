// Builds the prompt for a canvas generation/edit task. The authoring contract
// (imports, the `ph` data SDK, Quill/style rules, publish workflow) lives in
// the bundled canvas skills, which are installed in every local and cloud task
// — so the prompt only routes the agent into `building-canvases` and supplies
// the target-canvas context the skill needs. The standing instructions are
// wrapped in <canvas_generation_instructions> so the conversation UI collapses
// them into a single clickable tag (see extractCanvasInstructions).

// Short layout hints for legacy template ids whose richer prompt contracts
// were folded into the canvas skills. New canvases are all "freeform".
const TEMPLATE_HINTS: Record<string, string> = {
  dashboard:
    "Template: a live, data-driven dashboard — KPI cards with deltas, trend charts, and an " +
    "in-canvas date control, built with React + Quill.",
  "web-analytics":
    "Template: a PostHog-style web analytics board — visitors / page views / sessions / bounce " +
    "rate KPIs, a visitors-over-time chart, and top paths / sources / devices / geography " +
    "tables, backed by the web-analytics query kinds.",
};

export function buildCanvasGenerationPrompt(input: {
  /**
   * Target canvas, when the surface already knows it (canvas-initiated runs).
   * Channel-composer runs omit it and create a descriptively named canvas.
   */
  dashboardId?: string;
  /** The target's title; set whenever dashboardId is. */
  name?: string;
  channelName: string;
  /** Backend channel UUID, scoping the resolve-or-create canvas tools. */
  channelId: string;
  templateId?: string;
  instruction: string;
  /** True when editing an existing canvas (it already has published source). */
  isEdit: boolean;
  /** First builds only: point the agent at the known-good starter scaffold. */
  useStarter?: boolean;
}): string {
  const { dashboardId, name, channelName, templateId, instruction, isEdit } =
    input;

  // The header points back at the user's request, which leads the message —
  // without the pointer the agent can read the block as self-contained and
  // under-weight the actual instruction above it.
  const title = name ? ` "${name}"` : "";
  const header = dashboardId
    ? isEdit
      ? `Edit the canvas${title} in the channel "${channelName}", per the user's request at the start of this message.`
      : `Build the canvas${title} for the channel "${channelName}", per the user's request at the start of this message.`
    : `Build a canvas in the channel "${channelName}", per the user's request at the start of this message.`;

  // With a pre-resolved target the id is pinned. Target-less runs create
  // directly without exposing team-controlled canvas metadata to the agent.
  const targetBlock = dashboardId
    ? `Target canvas — already created, do NOT create another:
- canvas id: "${dashboardId}"
- channel: "${channelName}"`
    : `Target canvas — none is pre-created. Create one in channel "${input.channelId}" with
\`canvas-create\`, named with a short descriptive title drawn from the request — never "Untitled canvas".
Do not list or inspect other canvases to choose a target.`;

  const starterLine =
    !isEdit && input.useStarter
      ? dashboardId
        ? "\nStart from the starter scaffold in the building-react-quill-canvases skill's references — it already wires the date picker, theme tokens, and loading skeletons correctly.\n"
        : "\nFor a first build (a new or still-empty canvas), start from the starter scaffold in the building-react-quill-canvases skill's references — it already wires the date picker, theme tokens, and loading skeletons correctly.\n"
      : "";

  const templateHint = templateId ? TEMPLATE_HINTS[templateId] : undefined;
  const templateLine = templateHint ? `\n${templateHint}\n` : "";

  const instructions = `${header}

Invoke the \`building-canvases\` skill now and follow its workflow (and the companion canvas
skills it routes to) to implement, validate, and publish this canvas.

${targetBlock}
${templateLine}${starterLine}
Read the canvas's current source and \`current_version_id\` with the
\`canvas-source-retrieve\` tool before editing, and publish the COMPLETE
source project with \`canvas-publish-create\`, passing that version id as
\`expected_current_version_id\`. The canvas lives in PostHog, not on disk — publishing through
that tool is what saves it. Do not write local files and do not reply with the code.

Verify event/property names via the PostHog MCP tools before using them, and operate only on
this project.`;

  return `${instruction}

<canvas_generation_instructions>
${instructions}
</canvas_generation_instructions>`;
}
