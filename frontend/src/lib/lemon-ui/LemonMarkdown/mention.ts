// @ts-nocheck
import { findAndReplace } from 'mdast-util-find-and-replace'

import { RichContentNodeType } from 'lib/components/RichContentEditor/types'

// A member id is a user id; a role id is a role uuid.
const mentionRegex = new RegExp(
    /(?:^|\s)@(?:(member):(\d+)|(role):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))/,
    'gi'
)

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
    const replaceMention = (
        value: string,
        memberType: string | undefined,
        memberId: string | undefined,
        roleType: string | undefined,
        roleId: string | undefined
    ): MentionNode[] => {
        const mentionType = (memberType ?? roleType ?? '').toLowerCase()
        const id = memberId ?? roleId
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
