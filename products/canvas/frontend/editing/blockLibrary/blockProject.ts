import { BLOCK_ICONS_PATH, BLOCK_RUNTIME_PATH, componentPath } from './blockDefinitions'
import { withLibraryFile } from './blockLibrarySync'
import { BLOCK_COMPONENT_SOURCES } from './componentSources'
import { jsxOpeningTags, jsxStringAttribute } from './jsxOpeningTags'

export const CANVAS_ENTRY_PATH = 'src/canvas.tsx'

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
`

// Matches PostHog Desktop's "Blank" starter, so a blank canvas edits the same way in both apps.
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
`

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

function insightBlockIds(files: Record<string, string>): string[] {
    return Object.values(files).flatMap((source) =>
        jsxOpeningTags(source, 'Insight').flatMap(({ tag }) => {
            const id = jsxStringAttribute(source, tag, 'shortId')
            return id ? [id] : []
        })
    )
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

function usedComponents(source: string): string[] {
    return Array.from(source.matchAll(/from\s+["']\.\/blocks\/([A-Za-z]+)["']/g), (match) => match[1]).filter(
        (name) => !!BLOCK_COMPONENT_SOURCES[name]
    )
}

/** The files of a blank canvas built from blocks: a title, a date range, and the block library it needs. */
export function blankCanvasFiles(): Record<string, string> {
    let files = withLibraryFile({ 'index.html': ENTRY_HTML, [CANVAS_ENTRY_PATH]: BLANK_CANVAS }, BLOCK_RUNTIME_PATH)
    files = withLibraryFile(files, BLOCK_ICONS_PATH)
    for (const component of usedComponents(BLANK_CANVAS)) {
        files = withLibraryFile(files, componentPath(component))
    }
    return files
}
