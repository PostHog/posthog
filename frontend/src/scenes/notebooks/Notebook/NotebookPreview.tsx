import { Fragment } from 'react'

import { IconNotebook } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { JSONContent, RichContentNodeType } from 'lib/components/RichContentEditor/types'

import { NODE_ICONS } from '../nodeIcons'
import { NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'

const MARK_WRAPPERS: Record<string, (children: JSX.Element, attrs?: Record<string, any>) => JSX.Element> = {
    bold: (c) => <strong>{c}</strong>,
    italic: (c) => <em>{c}</em>,
    code: (c) => <code>{c}</code>,
    underline: (c) => <u>{c}</u>,
    strike: (c) => <s>{c}</s>,
    comment: (c) => <mark className="bg-fill-highlight-100">{c}</mark>,
    link: (c, attrs) => (
        <Link to={attrs?.href ?? '#'} target="_blank">
            {c}
        </Link>
    ),
}

// Read-only renderer for a notebook ProseMirror doc
// used to preview notebook content without mounting a full Tiptap editor.
export function NotebookPreview({ content }: { content: JSONContent | null | undefined }): JSX.Element {
    if (!content) {
        return <p className="text-secondary italic">Empty notebook</p>
    }
    return <div className="prose prose-sm max-w-none">{renderNode(content, 'root')}</div>
}

function renderNode(node: JSONContent, key: string): JSX.Element | null {
    // Mention is the one inline ph-* node — render as a span so it sits in a paragraph.
    if (node.type === RichContentNodeType.Mention) {
        return (
            <span key={key} className="bg-fill-highlight-100 px-1 rounded font-medium">
                @{node.attrs?.id ?? 'member'}
            </span>
        )
    }
    if (node.type?.startsWith('ph-')) {
        return <EmbedPlaceholder key={key} icon={pickIcon(node.type)} label={describeEmbed(node.type)} />
    }

    switch (node.type) {
        case 'text':
            return <Fragment key={key}>{applyMarks(<>{node.text}</>, node.marks)}</Fragment>
        case 'hardBreak':
            return <br key={key} />
        case 'doc':
            return <Fragment key={key}>{renderChildren(node, key)}</Fragment>
        case 'heading':
            return renderHeading(node, key)
        case 'paragraph':
            return <p key={key}>{renderChildren(node, key)}</p>
        case 'bulletList':
            return <ul key={key}>{renderListItems(node, key)}</ul>
        case 'orderedList':
            return <ol key={key}>{renderListItems(node, key)}</ol>
        case 'taskList':
            return (
                <ul key={key} className="list-none pl-0">
                    {renderTaskItems(node, key)}
                </ul>
            )
        case 'table':
            return (
                <table key={key} className="border-collapse">
                    <tbody>{renderChildren(node, key)}</tbody>
                </table>
            )
        case 'tableRow':
            return <tr key={key}>{renderChildren(node, key)}</tr>
        case 'tableHeader':
            return <th key={key}>{renderChildren(node, key)}</th>
        case 'tableCell':
            return <td key={key}>{renderChildren(node, key)}</td>
        case 'codeBlock':
            return (
                <pre key={key}>
                    <code>{renderChildren(node, key)}</code>
                </pre>
            )
        case 'blockquote':
            return <blockquote key={key}>{renderChildren(node, key)}</blockquote>
        case 'horizontalRule':
            return <hr key={key} />
        default:
            // Unknown node — recurse into children to avoid silently dropping content
            return node.content ? <Fragment key={key}>{renderChildren(node, key)}</Fragment> : null
    }
}

function renderHeading(node: JSONContent, key: string): JSX.Element {
    const level = Math.min(Math.max(node.attrs?.level ?? 1, 1), 6) as 1 | 2 | 3 | 4 | 5 | 6
    const Tag = `h${level}` as const
    return <Tag key={key}>{renderChildren(node, key)}</Tag>
}

function renderChildren(node: JSONContent, key: string): (JSX.Element | null)[] {
    return (node.content ?? []).map((child, i) => renderNode(child, `${key}-${i}`))
}

function renderListItems(node: JSONContent, key: string): JSX.Element[] {
    return (node.content ?? []).map((item, i) => <li key={`${key}-${i}`}>{renderChildren(item, `${key}-${i}`)}</li>)
}

function renderTaskItems(node: JSONContent, key: string): JSX.Element[] {
    return (node.content ?? []).map((item, i) => (
        <li key={`${key}-${i}`} className="flex items-start gap-2">
            <input type="checkbox" checked={!!item.attrs?.checked} disabled className="mt-1" />
            <div>{renderChildren(item, `${key}-${i}`)}</div>
        </li>
    ))
}

function applyMarks(element: JSX.Element, marks: JSONContent['marks']): JSX.Element {
    return (marks ?? []).reduce((wrapped, mark) => {
        const wrap = MARK_WRAPPERS[mark.type]
        return wrap ? wrap(wrapped, mark.attrs) : wrapped
    }, element)
}

function describeEmbed(type: string): string {
    return KNOWN_NODES[type]?.titlePlaceholder ?? type
}

function pickIcon(type: string): JSX.Element {
    return NODE_ICONS[type as NotebookNodeType] ?? <IconNotebook />
}

function EmbedPlaceholder({ icon, label }: { icon: JSX.Element; label: string }): JSX.Element {
    return (
        <div className="my-2 px-3 py-2 border rounded flex items-center gap-2 text-default text-sm">
            <span className="text-secondary text-lg">{icon}</span>
            <span>{label}</span>
        </div>
    )
}
