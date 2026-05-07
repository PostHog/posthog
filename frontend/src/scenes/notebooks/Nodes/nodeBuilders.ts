// Pure JSONContent factories for notebook nodes.
//
// Kept in a standalone module so callers (e.g. SlashCommands) can build node content without
// pulling in the node modules themselves. The node modules import `createPostHogWidgetNode` from
// `NodeWrapper`, and `NodeWrapper` imports `SlashCommandsPopover` from `SlashCommands` — putting
// the builders in either node module creates a circular import that surfaces as
// `createPostHogWidgetNode is not a function` at module-evaluation time.
import { JSONContent } from '@tiptap/core'

import { NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { InsightQueryNode } from '~/queries/schema/schema-general'

import { NotebookNodeType } from '../types'

export function buildNodeEmbed(): JSONContent {
    return {
        type: NotebookNodeType.Embed,
        attrs: {
            __init: {
                showSettings: true,
            },
        },
    }
}

export function buildNodeQueryContent(query: QuerySchema): JSONContent {
    return {
        type: NotebookNodeType.Query,
        attrs: {
            query: query,
            showSettings: true,
        },
    }
}

export function buildInsightVizQueryContent(source: InsightQueryNode): JSONContent {
    return buildNodeQueryContent({ kind: NodeKind.InsightVizNode, source: source })
}
