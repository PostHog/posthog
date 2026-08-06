// Builds the prompt for a canvas generation task kicked off from a notebook.
// A trimmed port of the desktop host's builder (products/desktop/packages/core/
// src/canvas/generationPrompt.ts): the authoring contract lives in the canvas
// skills bundled into every task sandbox, so the prompt only routes the agent
// into `building-canvases` and pins the target canvas.

export function buildCanvasGenerationPrompt(input: {
    canvasId: string
    name: string
    channelId: string
    instruction: string
    /** True when the canvas already has a published build. */
    isEdit: boolean
}): string {
    const { canvasId, name, channelId, instruction, isEdit } = input

    const header = isEdit
        ? `Edit the canvas "${name}" (in channel "${channelId}"), per the user's request at the start of this message.`
        : `Build the canvas "${name}" (in channel "${channelId}"), per the user's request at the start of this message.`

    const instructions = `${header}

Invoke the \`building-canvases\` skill now and follow its workflow (and the companion canvas
skills it routes to) to implement, validate, and publish this canvas.

Target canvas — already created, do NOT create another:
- canvas id: "${canvasId}"

Read the canvas's current source and \`current_version_id\` with the
\`canvas-source-retrieve\` tool before editing, and publish the COMPLETE
source project with \`canvas-publish-create\`, passing that version id as
\`expected_current_version_id\`. The canvas lives in PostHog, not on disk — publishing through
that tool is what saves it. Do not write local files and do not reply with the code.

Verify event/property names via the PostHog MCP tools before using them, and operate only on
this project.`

    return `${instruction}

<canvas_generation_instructions>
${instructions}
</canvas_generation_instructions>`
}
