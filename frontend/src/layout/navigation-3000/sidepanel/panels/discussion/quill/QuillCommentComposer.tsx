import { useActions, useValues } from 'kea'

import { Button, Kbd, KbdGroup } from '@posthog/quill'

import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { CommentsLogicProps, commentsLogic } from 'lib/components/Comments/commentsLogic'
import { scopeSyncsToSlack } from 'lib/components/Comments/commentUtils'
import { SlackDestinationPicker } from 'lib/components/Comments/SlackDestinationPicker'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconSlack } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LazyQuillCommentEditor } from './LazyQuillCommentEditor'

/** Writes a new comment, or a reply while one is in progress. The same logic state backs both. */
export function QuillCommentComposer({ logicProps }: { logicProps: CommentsLogicProps }): JSX.Element {
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
    } = useValues(commentsLogic)
    const {
        sendComposedContent,
        clearItemContext,
        setReplyingComment,
        setRichContentEditor,
        onRichContentEditorUpdate,
        setComposerSendToSlack,
        setComposerSlackIntegrationId,
        setComposerSlackChannel,
    } = useActions(commentsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Only a new top-level comment can go straight to Slack. Replies sync on their own.
    const showSlackToggle =
        !replyingCommentId &&
        !!featureFlags[FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC] &&
        scopeSyncsToSlack(logicProps.scope)

    const placeholder = replyingCommentId
        ? 'Reply'
        : `Comment on ${logicProps.item_id ? 'this ' : ''}${humanizeScope(logicProps.scope, !!logicProps.item_id).toLowerCase()}`

    const sendDisabledReason = isEmpty
        ? 'Write a message first'
        : composerSendToSlack && !composerSlackIntegrationId
          ? 'Select a Slack workspace'
          : composerSendToSlack && !composerSlackChannel
            ? 'Select a Slack channel'
            : null

    const send = (): void => {
        // Same guard as the button, because Cmd+Enter skips its disabled state.
        if (!sendDisabledReason && !isSendingComment) {
            sendComposedContent(false)
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <LazyQuillCommentEditor
                key={key}
                placeholder={placeholder}
                initialContent={currentComposerDraft}
                onCreate={setRichContentEditor}
                onUpdate={onRichContentEditorUpdate}
                onPressCmdEnter={send}
                disabled={isSendingComment}
                toolbarActions={
                    showSlackToggle && (
                        <Button
                            size="icon-sm"
                            aria-label="Send to a Slack channel"
                            tooltip="Send to a Slack channel"
                            aria-pressed={composerSendToSlack}
                            className="aria-pressed:bg-fill-selected aria-pressed:text-foreground"
                            onClick={() => setComposerSendToSlack(!composerSendToSlack)}
                            data-attr="discussions-comment-send-to-slack-toggle"
                        >
                            <IconSlack />
                        </Button>
                    )
                }
            />
            {composerSendToSlack && (
                <SlackDestinationPicker
                    integrationId={composerSlackIntegrationId}
                    channel={composerSlackChannel}
                    onIntegrationChange={setComposerSlackIntegrationId}
                    onChannelChange={setComposerSlackChannel}
                    className="rounded-md border border-border p-2"
                />
            )}
            <div className="flex flex-wrap items-center justify-end gap-2">
                <KbdGroup className="me-auto text-muted-foreground">
                    <Kbd>⌘</Kbd>
                    <Kbd>Enter</Kbd>
                </KbdGroup>
                {(itemContext || replyingCommentId) && (
                    <Button
                        variant="outline"
                        onClick={() => (itemContext ? clearItemContext() : setReplyingComment(null))}
                        data-attr="discussions-comment-cancel"
                    >
                        Cancel
                    </Button>
                )}
                {!replyingCommentId && (
                    <Button
                        variant="outline"
                        onClick={() => sendComposedContent(true)}
                        loading={isSendingComment}
                        disabledReason={
                            composerSendToSlack
                                ? 'Turn off sending to Slack to add a task'
                                : isEmpty
                                  ? 'Write a message first'
                                  : null
                        }
                        data-attr="discussions-comment-task"
                    >
                        Add as task
                    </Button>
                )}
                <Button
                    variant="primary"
                    onClick={send}
                    loading={isSendingComment}
                    disabledReason={sendDisabledReason}
                    data-attr="discussions-comment"
                >
                    {composerSendToSlack ? 'Send to Slack' : replyingCommentId ? 'Reply' : 'Comment'}
                </Button>
            </div>
        </div>
    )
}
