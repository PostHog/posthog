import { JSONContent } from 'lib/components/RichContentEditor/types'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { DocumentBlock } from '~/queries/schema/schema-assistant-artifacts'

import { visualizationTypeToQuery } from '../utils'
import { markdownToTiptap } from './markdownToTiptap'

/**
 * Convert DocumentBlock[] to tiptap JSONContent[] for notebook creation.
 */
export function blocksToTiptapContent(blocks: DocumentBlock[]): JSONContent[] {
    const result: JSONContent[] = []

    for (const block of blocks) {
        switch (block.type) {
            case 'markdown':
                // Convert markdown to proper tiptap JSON structure
                result.push(...markdownToTiptap(block.content))
                break
            case 'visualization': {
                // Create a ph-query node that the notebook can render
                const query = visualizationTypeToQuery(block)
                if (!query) {
                    break
                }

                result.push({
                    type: NotebookNodeType.Query,
                    attrs: {
                        query,
                        title: block.title,
                    },
                })
                break
            }
            case 'session_replay':
                result.push({
                    type: NotebookNodeType.Recording,
                    attrs: {
                        id: block.session_id,
                        __init: {
                            expanded: true,
                        },
                    },
                })
                break
        }
    }

    return result
}
