import { richContentToText } from 'lib/components/RichContentEditor/richContentText'
import { JSONContent } from 'lib/components/RichContentEditor/types'

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
        ? richContentToText(content, (userId) => {
              const member = members.find((member) => member.user.id === userId)
              return `@${member ? member.user.first_name : `user:${userId}`}`
          })
        : ''
}
