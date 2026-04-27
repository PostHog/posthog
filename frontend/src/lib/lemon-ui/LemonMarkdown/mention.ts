// @ts-nocheck
import { findAndReplace } from 'mdast-util-find-and-replace'

import { RichContentNodeType } from 'lib/components/RichContentEditor/types'

const mentionRegex = new RegExp(/(?:^|\s)@(member|role):(\d+)/, 'gi')

type MentionNode =
    | {
          type: 'text'
          value: string
      }
    | {
          type: RichContentNodeType
          data: {
              hName: string
              hProperties: Record<string, string>
          }
          children: never[]
      }

export default function remarkMentions() {
    const replaceMention = (value: string, mentionType: string, id: string): MentionNode[] => {
        const nodes = []

        // Separate leading white space
        if (value.indexOf('@') > 0) {
            nodes.push({
                type: 'text' as const,
                value: value.substring(0, value.indexOf('@')),
            })
        }

        nodes.push({
            type: RichContentNodeType.Mention,
            data: {
                hName: 'span',
                hProperties: {
                    'data-mention-type': mentionType,
                    'data-mention-id': String(id),
                    className: 'ph-mention',
                },
            },
            children: [],
        })

        return nodes
    }

    return (tree) => {
        findAndReplace(tree, [[mentionRegex, replaceMention]])
    }
}
