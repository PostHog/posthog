import { basename, join } from 'node:path'

import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { isInside } from '@/core/paths'
import type { Runtime } from '@/core/runtime'

import type { Product, ProductId } from './products'

const START = '<!-- posthog:setup:start -->'
const END = '<!-- posthog:setup:end -->'
const IN_PROGRESS = 'PostHog setup is in progress for this folder.'
// Claude Code reads CLAUDE.md, and a CLAUDE.md that imports AGENTS.md, on a line of its own or
// inside a sentence, already shows the block.
const IMPORTS_AGENTS_MD = /(^|\s)@(\.\/)?AGENTS\.md(?![\w.-])/m

export const AGENTS_FILE = 'AGENTS.md'
const CLAUDE_FILE = 'CLAUDE.md'

export interface WrittenFile {
    path: string
    status: 'created' | 'updated' | 'unchanged'
}

export function earlyBlock(): string {
    return [
        '## PostHog',
        '',
        `${IN_PROGRESS} Run \`hog setup\` to see the current step. Don't install PostHog any other way.`,
    ].join('\n')
}

interface UseCase {
    text: string
    // Each one adds its `hog learn` command to the line.
    products: readonly ProductId[]
    command?: string
    onlyWhenChosen?: boolean
}

const USE_CASES: readonly UseCase[] = [
    { text: 'Adding tracking for a new feature', products: ['product-analytics'] },
    { text: 'Feature flags and experiments', products: ['feature-flags', 'experiments'] },
    { text: 'Debugging errors (error tracking)', products: ['error-tracking'] },
    { text: 'Logs, metrics, and tracing (APM)', products: ['logs', 'metrics', 'tracing'] },
    { text: 'Querying data from other tools (data warehouse)', products: ['data-warehouse'] },
    { text: 'Tracking how agents use an MCP server (MCP analytics)', products: ['mcp-analytics'] },
    {
        text: 'Checking metrics or answering product questions',
        products: [],
        command: '`hog query run "<HogQL>"` (see `hog learn -s "query data"` for how to write HogQL)',
    },
    { text: 'AI observability (LLM analytics)', products: ['llm-analytics'], onlyWhenChosen: true },
]

// Lines for the products picked in the purpose step come first, in the order picked.
export function finalBlock(options: {
    host: string
    projectId: string
    products: readonly Product[]
    chosen: readonly ProductId[]
}): string {
    const { host, projectId, products, chosen } = options
    const command = (id: ProductId): string => `\`${products.find((product) => product.id === id)?.command}\``
    const lineFor = (useCase: UseCase): string =>
        `- ${useCase.text}: ${useCase.command ?? useCase.products.map(command).join(', ')}`

    const lines: string[] = []
    const listed = new Set<UseCase>()
    for (const id of chosen) {
        const useCase = USE_CASES.find((candidate) => candidate.products.includes(id))
        if (!useCase) {
            const label = products.find((product) => product.id === id)?.label ?? id
            lines.push(`- ${label}: ${command(id)}`)
        } else if (!listed.has(useCase)) {
            listed.add(useCase)
            lines.push(lineFor(useCase))
        }
    }

    for (const useCase of USE_CASES) {
        if (!listed.has(useCase) && !useCase.onlyWhenChosen) {
            lines.push(lineFor(useCase))
        }
    }

    return [
        '## PostHog',
        '',
        `This folder sends data to PostHog project ${projectId} on ${host}, set in \`posthog.json\`. Start PostHog tasks with these commands:`,
        '',
        ...lines,
        '- Anything else: `hog learn -s "<keywords>"`',
    ].join('\n')
}

async function readText(runtime: Runtime, path: string): Promise<string | undefined> {
    try {
        return await runtime.readFile(path)
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
            return undefined
        }
        throw error
    }
}

function findBlock(text: string): { start: number; end: number } | undefined {
    const start = text.indexOf(START)
    const end = start === -1 ? -1 : text.indexOf(END, start)
    return start === -1 || end === -1 ? undefined : { start, end: end + END.length }
}

function withBlock(path: string, text: string, body: string): string {
    const block = `${START}\n${body}\n${END}`
    const found = findBlock(text)
    if (found) {
        return `${text.slice(0, found.start)}${block}${text.slice(found.end)}`
    }
    if (text.includes(START) || text.includes(END)) {
        throw new HogError(
            'setup_block_broken',
            `${path} has only one of the two PostHog setup markers, ${START} and ${END}.`,
            `Remove the remaining marker from ${path}, then run \`hog setup next\` again.`
        )
    }
    if (text.trim() === '') {
        return `${block}\n`
    }
    return `${text.replace(/\n*$/, '')}\n\n${block}\n`
}

// The folder comes from a checkout, which can hold AGENTS.md or CLAUDE.md as a link. A link inside
// the folder, such as CLAUDE.md to AGENTS.md, is followed. A link that leaves the folder, or one to a
// missing file, is neither read nor written through.
async function destination(runtime: Runtime, root: string, path: string): Promise<string> {
    const target = await runtime.realPath(path).catch(() => undefined)
    if (target === undefined || !isInside(root, target)) {
        const where = target === undefined ? 'a missing file' : escapeControls(target)
        throw new HogError(
            'setup_file_outside_folder',
            `${escapeControls(path)} links to ${where}, outside ${escapeControls(root)}. hog doesn't write through links that leave the folder.`,
            `Replace ${basename(path)} with a regular file, or link it to a file inside ${escapeControls(root)}. Then run \`hog setup next\` again.`
        )
    }

    return target
}

async function writeOne(
    runtime: Runtime,
    file: { path: string; target: string; before: string | undefined },
    body: string
): Promise<WrittenFile> {
    const { path, target, before } = file
    const after = withBlock(path, before ?? '', body)
    if (after === before) {
        return { path, status: 'unchanged' }
    }

    await runtime.replaceFile(target, after)
    return { path, status: before === undefined ? 'created' : 'updated' }
}

// Everything outside the markers stays as it is. A CLAUDE.md linked to AGENTS.md already has the
// new block when it is read, so it counts as unchanged.
export async function writeBlock(runtime: Runtime, folder: string, body: string): Promise<WrittenFile[]> {
    const root = await runtime.realPath(folder)
    const [agentsPath, claudePath] = [join(folder, AGENTS_FILE), join(folder, CLAUDE_FILE)]
    const [agentsTarget, claudeTarget] = await Promise.all([
        destination(runtime, root, agentsPath),
        destination(runtime, root, claudePath),
    ])

    const agents = { path: agentsPath, target: agentsTarget, before: await readText(runtime, agentsTarget) }
    const written = [await writeOne(runtime, agents, body)]

    const claude = await readText(runtime, claudeTarget)
    if (claude !== undefined && (!IMPORTS_AGENTS_MD.test(claude) || findBlock(claude))) {
        written.push(await writeOne(runtime, { path: claudePath, target: claudeTarget, before: claude }, body))
    }

    return written
}

export async function blockStage(runtime: Runtime, folder: string): Promise<'early' | 'final' | undefined> {
    const text = await readText(runtime, join(folder, AGENTS_FILE))
    const found = text ? findBlock(text) : undefined
    if (!text || !found) {
        return undefined
    }
    return text.slice(found.start, found.end).includes(IN_PROGRESS) ? 'early' : 'final'
}
