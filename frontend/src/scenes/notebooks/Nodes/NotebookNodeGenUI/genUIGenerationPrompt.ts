import { GenUIFrameSchema } from './genUIFrames'

const GENERATED_NAME_MAX_LENGTH = 80

export function getGenUIName(prompt: string): string {
    const normalized = prompt.trim().replace(/\s+/g, ' ')
    if (!normalized) {
        return 'Custom visualization'
    }
    if (normalized.length <= GENERATED_NAME_MAX_LENGTH) {
        return normalized
    }
    return `${normalized.slice(0, GENERATED_NAME_MAX_LENGTH - 3).trimEnd()}...`
}

export function buildGenUIGenerationPrompt(input: {
    canvasId: string
    name: string
    instruction: string
    frames: GenUIFrameSchema[]
    missingFrames: string[]
    isEdit: boolean
}): string {
    const { canvasId, name, instruction, frames, missingFrames, isEdit } = input
    const frameContract = frames.length ? JSON.stringify(frames) : 'No dataframe preview is currently available.'
    const frameNames = [...new Set([...frames.map((frame) => frame.name), ...missingFrames])]
    const capabilityContract = JSON.stringify({
        posthog: { insights: [], inlineQueries: false, captureEvents: [] },
        network: { origins: [] },
        notebook: { frames: frameNames },
    })
    const missingContract = missingFrames.length
        ? `The requested frames without a saved result are: ${missingFrames.join(', ')}. Render a useful empty state if reading one fails.`
        : 'Every requested frame currently has a saved preview.'

    return `${instruction}

<genui_generation_instructions>
${isEdit ? 'Update' : 'Build'} the existing canvas "${name}" (id "${canvasId}") as a live embedded notebook visualization. Do not create another canvas. Publishing the canvas is the result; do not stop after generating source code in the task workspace.

Use the bundled \`building-canvases\` skill for the project format and validation rules.

Canvas operations are commands inside the PostHog MCP \`exec\` tool. In Claude, this tool is named \`mcp__posthog__exec\`. Do not use \`ToolSearch\` or try to call \`canvas-*\` names as standalone tools.

Follow this sequence:
1. Call \`mcp__posthog__exec\` with \`command: call canvas-source-retrieve {"id":"${canvasId}"}\`. Keep the returned \`current_version_id\`.
2. Build the complete source project.
3. Validate it through \`exec\` with a command starting \`call canvas-validate-create\` and a JSON object containing \`id\` and \`project\`.
4. Publish it through \`exec\` with a command starting \`call canvas-publish-create\` and a JSON object containing \`id\`, \`project\`, \`prompt\`, and the observed \`expected_current_version_id\`. Publish the new version live, not as a draft.
5. Check the build through \`exec\` with \`command: call canvas-builds-retrieve {"id":"${canvasId}"}\`. If it fails, fix the project and publish again.

Read notebook data only with \`await ph.readFrame(name)\`. It returns \`{ name, columns: [{ name, type }], rows: unknown[][], totalRowCount, includedRowCount, truncated }\`.

Set \`project.capabilities\` to exactly \`${capabilityContract}\`. Do not add PostHog or network capabilities. Never call \`fetch\`, \`ph.query\`, or \`ph.loadInsight\` for notebook dataframe data.

Requested frames: ${frameContract}

${missingContract}

Build a responsive, self-contained visualization without navigation or application chrome. Keep decorative assets self-contained instead of fetching them from external URLs. For 3D work, import \`three\` from the pinned platform dependencies, size the renderer with its container, and dispose animation frames, listeners, geometries, materials, textures, and the renderer on unmount. Show visible loading, error, empty, and truncated-data states where applicable.
</genui_generation_instructions>`
}
