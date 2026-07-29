import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonLabel } from '@posthog/lemon-ui'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonRichContentEditor } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CommentsLogicProps, commentsLogic } from './commentsLogic'

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
    } = useActions(commentsLogic(props))
    const { featureFlags } = useValues(featureFlagLogic)
    const { slackIntegrations } = useValues(integrationsLogic)

    // Toggling a brand-new top-level comment straight to Slack; replies sync automatically.
    const showSlackToggle = !replyingCommentId && !!featureFlags[FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC]
    const selectedIntegration = slackIntegrations?.find((integration) => integration.id === composerSlackIntegrationId)

    const placeholder = replyingCommentId
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
                onPressCmdEnter={() => {
                    // The send buttons are disabled when empty - the shortcut must not bypass that
                    if (!isEmpty) {
                        sendComposedContent(false)
                    }
                }}
                disabled={isSendingComment}
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
                !slackIntegrations?.length ? (
                    <SlackNotConfiguredBanner />
                ) : (
                    <div className="flex flex-col gap-2 rounded border border-border p-2">
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Slack workspace</LemonLabel>
                            <IntegrationChoice
                                integration="slack"
                                value={composerSlackIntegrationId ?? undefined}
                                onChange={(nextValue) => setComposerSlackIntegrationId(nextValue ?? null)}
                            />
                        </div>
                        {selectedIntegration ? (
                            <div className="flex flex-col gap-1">
                                <LemonLabel>Channel</LemonLabel>
                                <SlackChannelPicker
                                    value={composerSlackChannel ?? undefined}
                                    onChange={(nextValue) => setComposerSlackChannel(nextValue ?? null)}
                                    integration={selectedIntegration}
                                />
                            </div>
                        ) : null}
                    </div>
                )
            ) : null}
            <div className="flex justify-between items-center gap-2">
                <div className="flex-1" />
                {itemContext ? (
                    <LemonButton size={buttonSize} type="secondary" onClick={() => clearItemContext()}>
                        Cancel
                    </LemonButton>
                ) : null}
                {!replyingCommentId ? (
                    <LemonButton
                        size={buttonSize}
                        type="secondary"
                        onClick={() => sendComposedContent(true)}
                        loading={isSendingComment}
                        disabledReason={
                            composerSendToSlack
                                ? 'Turn off "Send to Slack" to add a task'
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
                    onClick={() => sendComposedContent(false)}
                    // Guard against double-submit: isSendingComment tracks the send (and the Slack
                    // send) lifecycle, disabling the button while it's in flight.
                    loading={isSendingComment}
                    disabledReason={primaryDisabledReason}
                    sideIcon={<KeyboardShortcut command enter />}
                    data-attr="discussions-comment"
                >
                    {composerSendToSlack ? 'Send to Slack' : `Add ${replyingCommentId ? 'reply' : 'comment'}`}
                </LemonButton>
            </div>
        </div>
    )
}
