import { v4 as uuidv4 } from 'uuid'

import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import type {
    NotebookComponentBlockNode,
    NotebookDocument,
    NotebookPropValue,
} from 'lib/components/MarkdownNotebook/types'

import {
    getAccountViewComponentByKind,
    getAccountViewComponentByTag,
    type AccountViewComponentKind,
} from '../../components/Accounts/accountViewComponents'
import type { AccountViewTileConfig } from '../../components/Accounts/accountViewTileConfig'
import type { AccountViewContentApi } from '../../generated/api.schemas'
import { AccountViewContentTypeEnumApi, AccountViewMarkdownNodeTypeEnumApi } from '../../generated/api.schemas'

export interface AccountViewComponentInstance {
    nodeId: string
    kind: AccountViewComponentKind
    title?: string
    config?: AccountViewTileConfig
}

export function createAccountViewComponentInstance(kind: AccountViewComponentKind): AccountViewComponentInstance {
    return { nodeId: uuidv4(), kind }
}

export function parseAccountViewContent(content: AccountViewContentApi): AccountViewComponentInstance[] {
    const markdown = content.content[0]?.attrs.markdown ?? ''
    return parseMarkdownNotebook(markdown).nodes.flatMap((node) => {
        if (node.type !== 'component') {
            return []
        }
        const definition = getAccountViewComponentByTag(node.tagName)
        const nodeId = node.props.nodeId
        const title = node.props.title
        const config = node.props.config
        if (!definition || typeof nodeId !== 'string') {
            return []
        }
        return [
            {
                nodeId,
                kind: definition.kind,
                title: typeof title === 'string' && title.trim() ? title : undefined,
                config:
                    config && typeof config === 'object' && !Array.isArray(config)
                        ? (config as AccountViewTileConfig)
                        : undefined,
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
                    ...(component.title ? { title: component.title } : {}),
                    ...(component.config ? { config: component.config as NotebookPropValue } : {}),
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
