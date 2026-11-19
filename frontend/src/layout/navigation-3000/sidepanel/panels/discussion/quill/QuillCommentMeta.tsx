import { router } from 'kea-router'

import { IconEye } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { getRecordingLinkInfo, isViewingRecording } from 'lib/components/Comments/commentUtils'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { CommentType } from '~/types'

/** The links and notes under a comment: its place in a recording, its Slack thread, and whether it was edited. */
export function QuillCommentMeta({ comment }: { comment: CommentType }): JSX.Element | null {
    const recordingLink = getRecordingLinkInfo(comment)
    const slackThread = comment.slack_thread
    const millisecondsIntoRecording = comment.item_context?.milliseconds_into_recording

    if (!recordingLink && !slackThread && !comment.version) {
        return null
    }

    const viewInRecording = (): void => {
        if (!recordingLink) {
            return
        }
        if (isViewingRecording(recordingLink.recordingId) && recordingLink.unixTimestampMillis) {
            router.actions.push(recordingLink.url)
        } else {
            window.location.href = recordingLink.url
        }
    }

    return (
        <div className="flex flex-wrap items-center gap-1 pt-1">
            {recordingLink && (
                <Button
                    size="sm"
                    variant="outline"
                    tooltip="View in recording"
                    onClick={viewInRecording}
                    data-attr="view-comment-in-recording-at-timestamp"
                >
                    <IconEye />
                    {millisecondsIntoRecording !== undefined ? (
                        <span translate="no">{colonDelimitedDuration(millisecondsIntoRecording / 1000, null)}</span>
                    ) : (
                        'View in recording'
                    )}
                </Button>
            )}
            {slackThread && (
                <Button
                    size="sm"
                    variant="outline"
                    tooltip="Open the synced Slack thread"
                    render={<LinkPrimitive to={slackThread.url} target="_blank" />}
                    data-attr="discussions-comment-open-in-slack"
                >
                    <IconSlack />
                    {slackThread.channel_name ? `#${slackThread.channel_name}` : 'Open in Slack'}
                </Button>
            )}
            {comment.version ? (
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Edited
                </Text>
            ) : null}
        </div>
    )
}
