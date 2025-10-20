import { generateText } from '@tiptap/core'

import { JSONContent, RichContentNodeType } from 'lib/components/RichContentEditor/types'
import { DEFAULT_EXTENSIONS } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'

import { OrganizationMemberType } from '~/types'

export const discussionsSlug = (): string => `${window.location.pathname}#panel=discussion`

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
