import { generateText } from '@tiptap/core'

import { JSONContent, RichContentNodeType } from 'lib/components/RichContentEditor/types'
import { DEFAULT_EXTENSIONS } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'

import { ActivityScope, OrganizationMemberType } from '~/types'

export const discussionsSlug = (scope?: string, itemId?: string | null): string => {
    // Generate proper slug based on scope and item_id when available
    if (scope && itemId) {
        if (scope === ActivityScope.REPLAY || scope === 'recording') {
            return `/replay/${itemId}#panel=discussion`
        }
        if (scope === ActivityScope.NOTEBOOK) {
            return `/notebook/${itemId}#panel=discussion`
        }
    }

    // Fallback to current pathname with discussion panel hash
    return `${window.location.pathname}#panel=discussion`
}

export const getTextContent = (content: JSONContent | undefined | null, members: OrganizationMemberType[]): string => {
    return content
        ? generateText(content, DEFAULT_EXTENSIONS, {
              textSerializers: {
                  [RichContentNodeType.Mention]: ({ node }) => {
                      const userId = node.attrs.id

                      const member = members.find((member) => member.user.id === userId)

                      return `@${member ? member.user.first_name : `user:${userId}`}`
                  },
              },
          })
        : ''
}
