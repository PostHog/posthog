import { BLOCK_RUNTIME_PATH } from './blockDefinitions'

export const CANVAS_ENTRY_PATH = 'src/canvas.tsx'

interface Capabilities {
    posthog?: {
        insights?: string[]
        inlineQueries?: boolean
        captureEvents?: string[]
        state?: string[]
        actions?: string[]
        agentRequests?: boolean
    }
    network?: { origins?: string[] }
    connectors?: unknown[]
}

const INSIGHT_BLOCK_ID = /<Insight\b[^>]*?\bshortId="([^"]+)"/g

function insightBlockIds(files: Record<string, string>): string[] {
    return Object.values(files).flatMap((source) => Array.from(source.matchAll(INSIGHT_BLOCK_ID), (match) => match[1]))
}

export function usesBlocks(files: Record<string, string>): boolean {
    return BLOCK_RUNTIME_PATH in files
}

const POSTHOG_DEFAULTS = {
    insights: [] as string[],
    captureEvents: [] as string[],
    actions: [] as string[],
    agentRequests: false,
}

export function canvasCapabilities(capabilities: unknown, files: Record<string, string>): Capabilities | undefined {
    const current = capabilities && typeof capabilities === 'object' ? (capabilities as Capabilities) : undefined
    if (!usesBlocks(files)) {
        return current?.posthog ? { ...current, posthog: { ...POSTHOG_DEFAULTS, ...current.posthog } } : current
    }
    const posthog = { ...POSTHOG_DEFAULTS, ...current?.posthog }
    return {
        ...current,
        posthog: {
            ...posthog,
            insights: Array.from(new Set([...posthog.insights, ...insightBlockIds(files)])),
            inlineQueries: true,
            state: Array.from(new Set([...(posthog.state ?? []), 'user'])),
        },
        network: current?.network ?? { origins: [] },
    }
}
