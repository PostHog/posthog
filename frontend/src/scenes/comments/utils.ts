import { generateText } from '@tiptap/core'

import { JSONContent, RichContentNodeType } from 'lib/components/RichContentEditor/types'
import { DEFAULT_EXTENSIONS } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'

import { ActivityScope, OrganizationMemberType } from '~/types'

import type { CommentSlackThreadRefApi } from 'products/platform_features/frontend/generated/api.schemas'

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

/**
 * A Slack message permalink, as "Copy link" produces. The backend parses it properly (and prefers
 * the parent `thread_ts` when the link points at a reply) — this only exists so the composer can
 * disable the button and hint before spending a request.
 */
const SLACK_THREAD_URL_RE = /^https:\/\/[\w-]+\.slack\.com\/archives\/[A-Z0-9]+\/p\d{10,}/

export const isSlackThreadUrl = (url: string | null | undefined): boolean =>
    !!url && SLACK_THREAD_URL_RE.test(url.trim())

/**
 * Import states that will never change again, so the UI can stop polling. An empty status is
 * terminal too: that's a discussion sent *to* Slack, which never runs an import.
 */
const TERMINAL_SLACK_IMPORT_STATUSES = new Set(['', 'complete', 'partial', 'failed'])

export const isSlackImportInProgress = (slackThread: CommentSlackThreadRefApi | null | undefined): boolean =>
    !!slackThread && !TERMINAL_SLACK_IMPORT_STATUSES.has(slackThread.import_status)

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
