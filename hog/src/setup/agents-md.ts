import { basename, join } from 'node:path'

import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { isInside } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import type { StacksConfig } from '@/stack/config'

import type { Product, ProductId } from './products'

const START = '<!-- posthog:setup:start -->'
const END = '<!-- posthog:setup:end -->'
const IN_PROGRESS = 'PostHog setup is in progress for this folder.'
const STACK_LINK = '- Stack instructions for `'
// Claude Code reads CLAUDE.md, and a CLAUDE.md that imports AGENTS.md, on a line of its own or
// inside a sentence, already shows the block.
const IMPORTS_AGENTS_MD = /(^|\s)@(\.\/)?AGENTS\.md(?![\w.-])/m

export const AGENTS_FILE = 'AGENTS.md'
const CLAUDE_FILE = 'CLAUDE.md'

export interface WrittenFile {
    path: string
    status: 'created' | 'updated' | 'unchanged'
}

export interface BlockEdit extends WrittenFile {
    target: string
    before?: string
    contents: string
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
    // Each one adds its `hog skills read` or `hog skills search` command to the line.
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
        command: '`hog query run "<HogQL>"` (see `hog skills search query data` for how to write HogQL)',
    },
    {
        text: "Sending PostHog's browser requests through the app's own domain (reverse proxy)",
        products: [],
        command: '`hog skills read instrument-reverse-proxy`',
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
        '- Anything else: `hog skills search <keywords>`',
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
    if (text.includes(START) || text.includes(END)) {
        if (!found || text.indexOf(START) !== text.lastIndexOf(START) || text.indexOf(END) !== text.lastIndexOf(END)) {
            throw new HogError(
                'setup_block_broken',
                `${path} has incomplete or repeated PostHog setup markers.`,
                `Keep one matching pair of markers or remove the broken markers from ${path}, then retry.`
            )
        }
        return `${text.slice(0, found.start)}${block}${text.slice(found.end)}`
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

function editBlock(
    file: { path: string; target: string; before: string | undefined },
    body: string | undefined,
    stacks: StacksConfig | undefined
): BlockEdit {
    const { path, target, before } = file
    const found = before && findBlock(before)
    const current = found && before ? before.slice(found.start + START.length, found.end - END.length).trim() : ''
    const bodyLines = (body ?? current).split('\n').filter((line) => !line.startsWith(STACK_LINK))
    const links = Object.entries(stacks ?? {}).map(([name, stack]) => {
        const url = stack.dir
            .split(/[\\/]/)
            .map((part) => encodeURIComponent(part).replaceAll('(', '%28').replaceAll(')', '%29'))
            .join('/')
        return `${STACK_LINK}${name}\`: [${AGENTS_FILE}](./${url}/${AGENTS_FILE})`
    })
    const content = [bodyLines.join('\n').trimEnd() || '## PostHog', links.join('\n')].filter(Boolean).join('\n\n')
    const after = withBlock(path, before ?? '', content)
    return {
        path,
        target,
        before,
        contents: after,
        status: after === before ? 'unchanged' : before === undefined ? 'created' : 'updated',
    }
}

// Everything outside the markers stays as it is. A CLAUDE.md linked to AGENTS.md already has the
// new block when it is read, so it counts as unchanged.
export async function blockEdits(
    runtime: Runtime,
    folder: string,
    body: string | undefined,
    stacks?: StacksConfig
): Promise<BlockEdit[]> {
    const root = await runtime.realPath(folder)
    const [agentsPath, claudePath] = [join(folder, AGENTS_FILE), join(folder, CLAUDE_FILE)]
    const [agentsTarget, claudeTarget] = await Promise.all([
        destination(runtime, root, agentsPath),
        destination(runtime, root, claudePath),
    ])

    const agents = { path: agentsPath, target: agentsTarget, before: await readText(runtime, agentsTarget) }
    const first = editBlock(agents, body, stacks)
    const edits = [first]
    const claude = claudeTarget === agentsTarget ? first.contents : await readText(runtime, claudeTarget)
    if (claude !== undefined && (!IMPORTS_AGENTS_MD.test(claude) || claude.includes(START) || claude.includes(END))) {
        edits.push(editBlock({ path: claudePath, target: claudeTarget, before: claude }, body, stacks))
    }
    return edits
}

export async function writeBlock(
    runtime: Runtime,
    folder: string,
    body: string | undefined,
    stacks?: StacksConfig
): Promise<WrittenFile[]> {
    const edits = await blockEdits(runtime, folder, body, stacks)
    for (const edit of edits) {
        if (edit.status !== 'unchanged') {
            await runtime.replaceFile(edit.target, edit.contents)
        }
    }
    return edits.map(({ path, status }) => ({ path, status }))
}

export async function blockStage(runtime: Runtime, folder: string): Promise<'early' | 'final' | undefined> {
    const text = await readText(runtime, join(folder, AGENTS_FILE))
    const found = text ? findBlock(text) : undefined
    if (!text || !found) {
        return undefined
    }
    const body = text.slice(found.start + START.length, found.end - END.length)
    if (body.includes(IN_PROGRESS)) {
        return 'early'
    }
    return body.split('\n').some((line) => line.trim() && line !== '## PostHog' && !line.startsWith(STACK_LINK))
        ? 'final'
        : undefined
}
