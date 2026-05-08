import { Fragment } from 'react'

import {
    IconBookmark,
    IconClockRewind,
    IconGraph,
    IconGroups,
    IconImage,
    IconMap,
    IconMessage,
    IconNotebook,
    IconPerson,
    IconRewindPlay,
    IconTestTube,
    IconToggle,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'

type EmbedDescriptor = { icon: JSX.Element; label: string }

// Render embeds as compact icon + label cards instead of mounting their full node view
const EMBED_NODES: Partial<Record<NotebookNodeType, EmbedDescriptor>> = {
    [NotebookNodeType.Query]: { icon: <IconGraph />, label: 'Insight' },
    [NotebookNodeType.Image]: { icon: <IconImage />, label: 'Image' },
    [NotebookNodeType.Recording]: { icon: <IconRewindPlay />, label: 'Session recording' },
    [NotebookNodeType.ReplayTimestamp]: { icon: <IconClockRewind />, label: 'Replay timestamp' },
    [NotebookNodeType.Person]: { icon: <IconPerson />, label: 'Person' },
    [NotebookNodeType.FeatureFlag]: { icon: <IconToggle />, label: 'Feature flag' },
    [NotebookNodeType.Experiment]: { icon: <IconTestTube />, label: 'Experiment' },
    [NotebookNodeType.Survey]: { icon: <IconMessage />, label: 'Survey' },
    [NotebookNodeType.Cohort]: { icon: <IconGroups />, label: 'Cohort' },
    [NotebookNodeType.Backlink]: { icon: <IconBookmark />, label: 'Backlink' },
    [NotebookNodeType.Map]: { icon: <IconMap />, label: 'Map' },
}

const MARK_WRAPPERS: Record<string, (children: JSX.Element, attrs?: Record<string, any>) => JSX.Element> = {
    bold: (c) => <strong>{c}</strong>,
    italic: (c) => <em>{c}</em>,
    code: (c) => <code>{c}</code>,
    underline: (c) => <u>{c}</u>,
    strike: (c) => <s>{c}</s>,
    link: (c, attrs) => (
        <Link to={attrs?.href ?? '#'} target="_blank">
            {c}
        </Link>
    ),
}

/**
 * Read-only React renderer for a notebook ProseMirror JSON document.
 * Used where mounting a full Tiptap editor is overkill.
 * Walks the doc tree and renders block + inline nodes as plain HTML elements.
 */
export function NotebookPreview({ content }: { content: JSONContent | null | undefined }): JSX.Element {
    if (!content) {
        return <p className="text-secondary italic">Empty notebook</p>
    }
    return <div className="prose prose-sm max-w-none">{renderNode(content, 'root')}</div>
}

function renderNode(node: JSONContent, key: string): JSX.Element | null {
    const embed = node.type ? EMBED_NODES[node.type as NotebookNodeType] : undefined
    if (embed) {
        return <EmbedPlaceholder key={key} {...embed} label={describeEmbed(node, embed.label)} />
    }
    // Unknown PostHog-widget node — at least show that something was here.
    if (node.type?.startsWith('ph-')) {
        return <EmbedPlaceholder key={key} icon={<IconNotebook />} label={node.type} />
    }

    switch (node.type) {
        case 'doc':
            return <Fragment key={key}>{renderChildren(node, key)}</Fragment>
        case 'heading':
            return renderHeading(node, key)
        case 'paragraph':
            return <p key={key}>{renderInline(node.content, key)}</p>
        case 'bulletList':
            return <ul key={key}>{renderListItems(node, key)}</ul>
        case 'orderedList':
            return <ol key={key}>{renderListItems(node, key)}</ol>
        case 'codeBlock':
            return (
                <pre key={key}>
                    <code>{renderInline(node.content, key)}</code>
                </pre>
            )
        case 'blockquote':
            return <blockquote key={key}>{renderChildren(node, key)}</blockquote>
        case 'horizontalRule':
            return <hr key={key} />
        default:
            // Unknown block - recurse into children to avoid dropping content
            return node.content ? <Fragment key={key}>{renderChildren(node, key)}</Fragment> : null
    }
}

function renderHeading(node: JSONContent, key: string): JSX.Element {
    const level = clamp(node.attrs?.level ?? 1, 1, 6) as 1 | 2 | 3 | 4 | 5 | 6
    const Tag = `h${level}` as const
    return <Tag key={key}>{renderInline(node.content, key)}</Tag>
}

function renderChildren(node: JSONContent, key: string): (JSX.Element | null)[] {
    return (node.content ?? []).map((child, i) => renderNode(child, `${key}-${i}`))
}

function renderListItems(node: JSONContent, key: string): JSX.Element[] {
    return (node.content ?? []).map((item, i) => <li key={`${key}-${i}`}>{renderChildren(item, `${key}-${i}`)}</li>)
}

function renderInline(nodes: JSONContent[] | undefined, keyPrefix: string): JSX.Element[] {
    return (nodes ?? []).map((n, i) => {
        const k = `${keyPrefix}-${i}`
        if (n.type === 'text') {
            return <Fragment key={k}>{applyMarks(<>{n.text}</>, n.marks)}</Fragment>
        }
        if (n.type === 'hardBreak') {
            return <br key={k} />
        }
        return <Fragment key={k}>{renderInline(n.content, k)}</Fragment>
    })
}

function applyMarks(element: JSX.Element, marks: JSONContent['marks']): JSX.Element {
    return (marks ?? []).reduce((wrapped, mark) => {
        const wrap = MARK_WRAPPERS[mark.type]
        return wrap ? wrap(wrapped, mark.attrs) : wrapped
    }, element)
}

// Embed labels can pick up extra context from node attrs (e.g. an insight's shortId).
function describeEmbed(node: JSONContent, fallback: string): string {
    if (node.type === NotebookNodeType.Query) {
        const q = node.attrs?.query
        return q?.shortId ? `${fallback}: ${q.shortId}` : q?.kind ? `${fallback}: ${q.kind}` : fallback
    }
    return fallback
}

function EmbedPlaceholder({ icon, label }: EmbedDescriptor): JSX.Element {
    return (
        <div className="my-2 px-3 py-2 border rounded flex items-center gap-2 text-default text-sm">
            <span className="text-secondary text-lg">{icon}</span>
            <span>{label}</span>
        </div>
    )
}

function clamp(n: number, min: number, max: number): number {
    return Math.min(Math.max(n, min), max)
}
