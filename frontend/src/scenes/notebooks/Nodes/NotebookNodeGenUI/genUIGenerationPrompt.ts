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
    channelId: string
    instruction: string
    frames: GenUIFrameSchema[]
    missingFrames: string[]
    isEdit: boolean
}): string {
    const { canvasId, name, channelId, instruction, frames, missingFrames, isEdit } = input
    const frameContract = frames.length
        ? JSON.stringify(frames, null, 2)
        : 'No dataframe preview is currently available.'
    const missingContract = missingFrames.length
        ? `The requested frames without a saved result are: ${missingFrames.join(', ')}. Render a useful empty state if reading one fails.`
        : 'Every requested frame currently has a saved preview.'

    return `${instruction}

<genui_generation_instructions>
${isEdit ? 'Update' : 'Build'} the canvas "${name}" in channel "${channelId}" as an embedded notebook visualization.

Invoke the \`building-canvases\` skill and follow its workflow. The target canvas already exists:
- canvas id: "${canvasId}"

Read its source and \`current_version_id\` with \`canvas-source-retrieve\`. Validate the complete project, then publish it with \`canvas-publish-create\` and the observed version id. The user requested this notebook visualization, so make the new version live rather than leaving a draft. Do not create another canvas or write local files.

Notebook data is available only through \`await ph.readFrame(name)\`. It returns:
\`{ name, columns: [{ name, type }], rows: unknown[][], totalRowCount, includedRowCount, truncated }\`.

Declare every literal frame name you read in \`capabilities.notebook.frames\`. Keep PostHog query, capture, and network capabilities disabled unless the user's request explicitly needs them. Never call \`fetch\`, \`ph.query\`, or \`ph.loadInsight\` for notebook dataframe data.

Requested dataframe schemas and preview sizes:
${frameContract}

${missingContract}

Build a responsive, self-contained visualization without navigation or application chrome. For 3D work, import \`three\` from the pinned platform dependencies, size the renderer with its container, and dispose animation frames, listeners, geometries, materials, textures, and the renderer on unmount. Show visible loading, error, empty, and truncated-data states where applicable.
</genui_generation_instructions>`
}
