import { v4 as uuidv4 } from 'uuid'

import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import type { NotebookComponentBlockNode, NotebookDocument } from 'lib/components/MarkdownNotebook/types'

import {
    getAccountViewComponentByKind,
    getAccountViewComponentByTag,
    type AccountViewComponentKind,
} from '../../components/Accounts/accountViewComponents'
import type { AccountViewContentApi } from '../../generated/api.schemas'
import { AccountViewContentTypeEnumApi, AccountViewMarkdownNodeTypeEnumApi } from '../../generated/api.schemas'

export interface AccountViewComponentInstance {
    nodeId: string
    kind: AccountViewComponentKind
    span: number
}

export function createAccountViewComponentInstance(kind: AccountViewComponentKind): AccountViewComponentInstance {
    return { nodeId: uuidv4(), kind, span: 12 }
}

export function parseAccountViewContent(content: AccountViewContentApi): AccountViewComponentInstance[] {
    const markdown = content.content[0]?.attrs.markdown ?? ''
    return parseMarkdownNotebook(markdown).nodes.flatMap((node) => {
        if (node.type !== 'component') {
            return []
        }
        const definition = getAccountViewComponentByTag(node.tagName)
        const nodeId = node.props.nodeId
        const span = node.props.span
        if (!definition || typeof nodeId !== 'string') {
            return []
        }
        return [
            {
                nodeId,
                kind: definition.kind,
                span: typeof span === 'number' && Number.isInteger(span) && span >= 1 && span <= 12 ? span : 12,
            },
        ]
    })
}

export function createAccountViewContent(components: AccountViewComponentInstance[]): AccountViewContentApi {
    const document: NotebookDocument = {
        type: 'doc',
        errors: [],
        nodes: components.map(
            (component): NotebookComponentBlockNode => ({
                id: component.nodeId,
                type: 'component',
                tagName: getTagName(component.kind),
                props: {
                    nodeId: component.nodeId,
                    ...(component.span === 12 ? {} : { span: component.span }),
                },
            })
        ),
    }
    return {
        type: AccountViewContentTypeEnumApi.Doc,
        content: [
            {
                type: AccountViewMarkdownNodeTypeEnumApi.PhMarkdownNotebook,
                attrs: {
                    nodeId: 'markdown-notebook-v2',
                    markdown: serializeMarkdownNotebook(document),
                },
            },
        ],
    }
}

function getTagName(kind: AccountViewComponentKind): string {
    const definition = getAccountViewComponentByKind(kind)
    if (!definition) {
        throw new Error(`Unknown account view component: ${kind}`)
    }
    return definition.tagName
}
