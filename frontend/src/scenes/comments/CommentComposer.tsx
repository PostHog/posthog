import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonRichContentEditor } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CommentsLogicProps, commentsLogic } from './commentsLogic'
import { SlackDestinationPicker } from './SlackDestinationPicker'
import { SlackThreadImportPanel } from './SlackThreadImportPanel'
import { isSlackThreadUrl } from './utils'

export type CommentComposerProps = CommentsLogicProps & {
    /** The footer variant swaps to a "New comment" button while a reply is in progress; 'inline-reply' renders inside the thread */
    variant?: 'footer' | 'inline-reply'
}

export const CommentComposer = ({ variant = 'footer', ...props }: CommentComposerProps): JSX.Element => {
    const {
        key,
        isSendingComment,
        replyingCommentId,
        itemContext,
        isEmpty,
        currentComposerDraft,
        composerSendToSlack,
        composerSlackIntegrationId,
        composerSlackChannel,
        composerSlackMode,
        composerSlackThreadUrl,
        isImportingSlackThread,
    } = useValues(commentsLogic(props))
    const {
        sendComposedContent,
        clearItemContext,
        setRichContentEditor,
        onRichContentEditorUpdate,
        startNewComment,
        setComposerSendToSlack,
        setComposerSlackIntegrationId,
        setComposerSlackChannel,
        setComposerSlackMode,
        setComposerSlackThreadUrl,
        importSlackThread,
    } = useActions(commentsLogic(props))
    const { featureFlags } = useValues(featureFlagLogic)

    // Toggling a brand-new top-level comment straight to Slack; replies sync automatically.
    const showSlackToggle = !replyingCommentId && !!featureFlags[FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC]
    // Importing a thread doesn't use the editor at all — it reads a pasted Slack link instead.
    const isImportMode = showSlackToggle && composerSendToSlack && composerSlackMode === 'import'
    const importDisabledReason = !composerSlackIntegrationId
        ? 'Select a Slack workspace'
        : !isSlackThreadUrl(composerSlackThreadUrl)
          ? 'Paste a link to a Slack message'
          : null

    const placeholder = isImportMode
        ? 'The imported Slack thread starts the discussion'
        : replyingCommentId
          ? 'Reply...'
          : `Comment on ${props.item_id ? 'this ' : ''}${humanizeScope(props.scope, !!props.item_id)}`

    useEffect(() => {
        // Only the footer owns the item context - the inline reply composer unmounting must not wipe it
        if (variant !== 'footer') {
            return
        }
        // Whenever the discussion context changes or we fully unmount we clear the item context
        return () => clearItemContext()
        // oxlint-disable-next-line exhaustive-deps
    }, [key, variant, clearItemContext])

    if (variant === 'footer' && replyingCommentId) {
        // The composer is rendered inline in the thread being replied to - offer a way back
        return (
            <div className="flex justify-end pt-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => startNewComment()}
                    data-attr="discussions-new-comment"
                >
                    New comment
                </LemonButton>
            </div>
        )
    }

    const buttonSize = variant === 'inline-reply' ? 'small' : undefined

    const primaryDisabledReason = isEmpty
        ? 'No message'
        : composerSendToSlack && !composerSlackIntegrationId
          ? 'Select a Slack workspace'
          : composerSendToSlack && !composerSlackChannel
            ? 'Select a Slack channel'
            : null

    return (
        <div className="flex flex-col gap-2">
            <LemonRichContentEditor
                key={key}
                logicKey="discussions"
                placeholder={placeholder}
                initialContent={currentComposerDraft}
                onCreate={setRichContentEditor}
                onUpdate={onRichContentEditorUpdate}
                // Same guard as the primary button — otherwise the shortcut silently posts a
                // plain comment while "Send to Slack" is toggled on without a channel picked.
                onPressCmdEnter={() => {
                    if (isImportMode) {
                        if (!importDisabledReason && !isImportingSlackThread) {
                            importSlackThread()
                        }
                        return
                    }
                    if (!primaryDisabledReason && !isSendingComment) {
                        sendComposedContent(false)
                    }
                }}
                // Inert while importing a thread: the discussion's first message comes from Slack,
                // not from here. The Slack toggle lives in footerActions and stays clickable.
                disabled={isSendingComment || isImportMode}
                footerActions={
                    showSlackToggle ? (
                        <LemonButton
                            size="small"
                            icon={<IconSlack />}
                            active={composerSendToSlack}
                            onClick={() => setComposerSendToSlack(!composerSendToSlack)}
                            tooltip="Send this comment to a Slack channel"
                            data-attr="discussions-comment-send-to-slack-toggle"
                        />
                    ) : null
                }
            />
            {composerSendToSlack ? (
                <div className="flex flex-col gap-2 rounded border border-border p-2">
                    <LemonSegmentedButton
                        size="small"
                        value={composerSlackMode}
                        onChange={setComposerSlackMode}
                        options={[
                            { value: 'send', label: 'Send this comment' },
                            { value: 'import', label: 'Import a thread' },
                        ]}
                    />
                    {composerSlackMode === 'import' ? (
                        <SlackThreadImportPanel
                            integrationId={composerSlackIntegrationId}
                            threadUrl={composerSlackThreadUrl}
                            onIntegrationChange={setComposerSlackIntegrationId}
                            onThreadUrlChange={setComposerSlackThreadUrl}
                        />
                    ) : (
                        <SlackDestinationPicker
                            integrationId={composerSlackIntegrationId}
                            channel={composerSlackChannel}
                            onIntegrationChange={setComposerSlackIntegrationId}
                            onChannelChange={setComposerSlackChannel}
                        />
                    )}
                </div>
            ) : null}
            <div className="flex justify-between items-center gap-2">
                <div className="flex-1" />
                {itemContext ? (
                    <LemonButton size={buttonSize} type="secondary" onClick={() => clearItemContext()}>
                        Cancel
                    </LemonButton>
                ) : null}
                {/* Import mode has no composed content to turn into a task. */}
                {!replyingCommentId && !isImportMode ? (
                    <LemonButton
                        size={buttonSize}
                        type="secondary"
                        onClick={() => sendComposedContent(true)}
                        loading={isSendingComment}
                        disabledReason={
                            composerSendToSlack
                                ? 'Turn off the Slack toggle to add a task'
                                : isEmpty
                                  ? 'No message'
                                  : null
                        }
                        data-attr="discussions-comment-task"
                    >
                        Add as task
                    </LemonButton>
                ) : null}
                <LemonButton
                    size={buttonSize}
                    type="primary"
                    onClick={() => (isImportMode ? importSlackThread() : sendComposedContent(false))}
                    // Guard against double-submit: isSendingComment tracks the send (and the Slack
                    // send) lifecycle, disabling the button while it's in flight.
                    loading={isImportMode ? isImportingSlackThread : isSendingComment}
                    // Import mode deliberately ignores `isEmpty` — the editor body isn't used.
                    disabledReason={isImportMode ? importDisabledReason : primaryDisabledReason}
                    sideIcon={<KeyboardShortcut command enter />}
                    data-attr={isImportMode ? 'discussions-import-slack-thread' : 'discussions-comment'}
                >
                    {isImportMode
                        ? 'Import thread'
                        : composerSendToSlack
                          ? 'Send to Slack'
                          : `Add ${replyingCommentId ? 'reply' : 'comment'}`}
                </LemonButton>
            </div>
        </div>
    )
}
