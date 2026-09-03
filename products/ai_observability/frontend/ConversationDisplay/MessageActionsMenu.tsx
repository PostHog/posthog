import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import type { MutableRefObject } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AccessControlLevel, AccessControlResourceType, ActivityScope, SidePanelTab } from '~/types'

import { messageActionsMenuLogic } from './messageActionsMenuLogic'
import { useMessageActionsMenuContext } from './MessageActionsMenuProvider'
import { TranslatePopover } from './TranslatePopover'

const MAX_EDITOR_RETRIES = 10
const EDITOR_RETRY_DELAY_MS = 100
const MAX_QUOTE_LENGTH = 500

export interface MessageActionsMenuProps {
    content: string
    traceId?: string | null
    menuKey?: string
}

const ActiveMessageActionsMenu = ({
    content,
    traceId,
    startVisible,
    triggerRef,
}: MessageActionsMenuProps & {
    startVisible: boolean
    triggerRef?: MutableRefObject<HTMLButtonElement | null>
}): JSX.Element | null => {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const commentsLogicProps = {
        scope: ActivityScope.LLM_TRACE,
        item_id: traceId || '',
    }
    const commentsLogicInstance = commentsLogic(commentsLogicProps)
    const { maybeLoadComments, startNewComment } = useActions(commentsLogicInstance)

    const logic = messageActionsMenuLogic({ content })
    const { showConsentPopover, dataProcessingAccepted } = useValues(logic)
    const { setShowTranslatePopover, setShowConsentPopover } = useActions(logic)

    if (!content || content.trim().length === 0) {
        return null
    }

    const insertQuoteIntoEditor = (quotedContent: string, retries = 0): void => {
        // The logic can be unmounted before this deferred callback runs (e.g. the user navigates
        // away or switches traces), so bail out rather than reading `.values` off a torn-down store.
        if (!commentsLogicInstance.isMounted()) {
            return
        }
        // Access editor via .values to get the latest value at retry time, not render time
        const editor = commentsLogicInstance.values.richContentEditor
        if (editor) {
            editor.clear()
            editor.pasteContent(0, quotedContent + '\n\n')
            editor.focus('end')
        } else if (retries < MAX_EDITOR_RETRIES) {
            setTimeout(() => insertQuoteIntoEditor(quotedContent, retries + 1), EDITOR_RETRY_DELAY_MS)
        }
    }

    const handleStartDiscussion = (): void => {
        maybeLoadComments()
        // Exit any in-progress reply and deregister its editor, so the retry loop below
        // waits for the footer composer instead of pasting into a thread's reply composer
        startNewComment()
        openSidePanel(SidePanelTab.Discussion)

        const truncatedContent =
            content.length > MAX_QUOTE_LENGTH ? content.substring(0, MAX_QUOTE_LENGTH) + '...' : content

        const quotedContent = truncatedContent
            .split('\n')
            .map((line) => `> ${line}`)
            .join('\n')

        setTimeout(() => insertQuoteIntoEditor(quotedContent), EDITOR_RETRY_DELAY_MS)
    }

    const showDiscussions = !!traceId

    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmAnalytics,
        AccessControlLevel.Editor
    )

    const menuItems: LemonMenuItems = [
        ...(showDiscussions
            ? [
                  {
                      label: 'Start discussion',
                      onClick: handleStartDiscussion,
                      'data-attr': 'llma-message-start-discussion',
                  },
              ]
            : []),
        {
            label: 'Translate',
            disabledReason: accessControlDisabledReason ?? undefined,
            onClick: () => {
                if (dataProcessingAccepted) {
                    setShowTranslatePopover(true)
                } else {
                    setShowConsentPopover(true)
                }
            },
            'data-attr': 'llma-message-translate',
        },
    ]

    if (menuItems.length === 0) {
        return null
    }

    const handleConsentApproved = (): void => {
        setShowConsentPopover(false)
        setShowTranslatePopover(true)
    }

    // The popover anchors below are empty elements. Wrap them with the trigger so they do not become
    // gap-separated items of the toolbar row, which would shift this button relative to inactive ones.
    return (
        <div className="flex">
            <LemonMenu ref={triggerRef} items={menuItems} placement="bottom-end" startVisible={startVisible}>
                <LemonButton
                    size="small"
                    noPadding
                    icon={<IconEllipsis />}
                    tooltip="More actions"
                    data-attr="llma-message-actions-trigger"
                    data-menu-mounted="true"
                />
            </LemonMenu>

            {/* AI consent popover - shown first if user hasn't consented */}
            <AIConsentPopoverWrapper
                showArrow
                onApprove={handleConsentApproved}
                onDismiss={() => setShowConsentPopover(false)}
                hidden={!showConsentPopover}
            >
                <div />
            </AIConsentPopoverWrapper>

            {/* Translate popover - only shown after consent */}
            <TranslatePopover content={content} title="Translate message" />
        </div>
    )
}

export function MessageActionsMenu({
    content,
    traceId,
    menuKey = 'standalone',
}: MessageActionsMenuProps): JSX.Element | null {
    const sharedMenu = useMessageActionsMenuContext()
    const triggerRef = useRef<HTMLButtonElement | null>(null)
    const isActive = !sharedMenu || sharedMenu.activeMenuKey === menuKey
    const shouldRestoreFocus = !!sharedMenu && isActive
    // Only the active menu renders the translation UI, but its logic must outlive the menu, or a
    // translation is lost and fetched again each time the shared menu moves to another message.
    useMountedLogic(messageActionsMenuLogic({ content }))

    useEffect(() => {
        if (shouldRestoreFocus) {
            triggerRef.current?.focus()
        }
    }, [shouldRestoreFocus])

    if (!content || content.trim().length === 0) {
        return null
    }

    if (!isActive) {
        return (
            <LemonButton
                ref={triggerRef}
                size="small"
                noPadding
                icon={<IconEllipsis />}
                tooltip="More actions"
                aria-haspopup="true"
                data-attr="llma-message-actions-trigger"
                onClick={() => sharedMenu?.setActiveMenuKey(menuKey)}
            />
        )
    }

    return (
        <ActiveMessageActionsMenu
            content={content}
            traceId={traceId}
            startVisible={!!sharedMenu}
            triggerRef={triggerRef}
        />
    )
}
