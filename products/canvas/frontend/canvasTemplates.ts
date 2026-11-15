// Mirrors PostHog Desktop's built-in canvas templates. The backend exposes no template
// endpoint, so the picker reads this list.

// pinned: template id stored on the canvas record and read by the generation prompt
export const FREEFORM_TEMPLATE_ID = 'freeform'

// Default name for a new canvas, and the marker that it is still safe to auto-name.
export const UNTITLED_CANVAS_NAME = 'Untitled canvas'

export interface CanvasTemplate {
    id: string
    name: string
    description: string
}

export const CANVAS_TEMPLATES: CanvasTemplate[] = [
    {
        id: FREEFORM_TEMPLATE_ID,
        name: 'Freeform (React)',
        description: 'Describe anything. The agent writes a React app that runs in a sandbox and can be shared.',
    },
]

export function isPlaceholderCanvasName(name: string): boolean {
    const trimmed = name.trim()
    return trimmed === UNTITLED_CANVAS_NAME || trimmed === 'Untitled dashboard'
}
