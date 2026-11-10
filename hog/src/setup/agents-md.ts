import { join } from 'node:path'

import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'

import type { Product } from './products'

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
        `${IN_PROGRESS} Run \`hog setup\` to see the current step and continue. Do not install PostHog another way.`,
    ].join('\n')
}

interface UseCase {
    text: string
    products: readonly string[]
    command?: string
    onlyWhenChosen?: boolean
}

const USE_CASES: readonly UseCase[] = [
    { text: 'Adding tracking for a new feature', products: ['product-analytics', 'web-analytics'] },
    { text: 'Feature flags and experiments', products: ['feature-flags', 'experiments'] },
    { text: 'Debugging errors (error tracking)', products: ['error-tracking'] },
    {
        text: 'Checking metrics or answering product questions',
        products: [],
        command: '`hog query run "<HogQL>"`, with `hog learn -s "query data"` for how to write the query',
    },
    { text: 'LLM analytics', products: ['llm-analytics'], onlyWhenChosen: true },
]

// Lines for the products picked in the purpose step come first, in the order picked.
export function finalBlock(options: {
    host: string
    projectId: string
    products: readonly Product[]
    chosen: readonly string[]
}): string {
    const { host, projectId, products, chosen } = options
    const command = (id: string): string => {
        const product = products.find((candidate) => candidate.id === id)
        return `\`${product?.command ?? `hog learn -s "${id.replaceAll('-', ' ')}"`}\``
    }
    const lineFor = (useCase: UseCase): string =>
        `- ${useCase.text}: ${useCase.command ?? command(useCase.products[0] ?? '')}`
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
        `This folder sends data to PostHog project ${projectId} on ${host}, as posthog.json says. Start PostHog work here with these commands:`,
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
            `${path} has only one of the PostHog setup markers, ${START} and ${END}.`,
            `Remove the marker that is left from ${path}, then run \`hog setup next\` again.`
        )
    }
    if (text.trim() === '') {
        return `${block}\n`
    }
    return `${text.replace(/\n*$/, '')}\n\n${block}\n`
}

async function writeOne(runtime: Runtime, path: string, body: string): Promise<WrittenFile> {
    const before = await readText(runtime, path)
    const after = withBlock(path, before ?? '', body)
    if (after === before) {
        return { path, status: 'unchanged' }
    }
    await runtime.writeFile(path, after)
    return { path, status: before === undefined ? 'created' : 'updated' }
}

// Everything outside the markers stays as it is. A CLAUDE.md linked to AGENTS.md already has the
// new block when hog reads it, so it counts as unchanged.
export async function writeBlock(runtime: Runtime, folder: string, body: string): Promise<WrittenFile[]> {
    const written = [await writeOne(runtime, join(folder, AGENTS_FILE), body)]
    const claudePath = join(folder, CLAUDE_FILE)
    const claude = await readText(runtime, claudePath)
    if (claude !== undefined && (!IMPORTS_AGENTS_MD.test(claude) || findBlock(claude))) {
        written.push(await writeOne(runtime, claudePath, body))
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
