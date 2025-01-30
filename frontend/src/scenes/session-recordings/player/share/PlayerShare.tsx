import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { SharingModalContent } from 'lib/components/Sharing/SharingModal'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { playerShareLogic, PlayerShareLogicProps } from './playerShareLogic'

function TimestampForm(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { shareUrl } = useValues(logic)
    const { setShareUrlValue, submitShareUrl } = useActions(logic)

    return (
        <Form logic={playerShareLogic} props={props} formKey="shareUrl">
            <div className="flex gap-2 items-center">
                <LemonField name="includeTime">
                    <LemonCheckbox label="Start at" />
                </LemonField>
                <LemonField name="time" inline>
                    <LemonInput
                        className={clsx('w-20', { 'opacity-50': !shareUrl.includeTime })}
                        placeholder="00:00"
                        onFocus={() => setShareUrlValue('includeTime', true)}
                        onBlur={() => submitShareUrl()}
                        fullWidth={false}
                        size="small"
                    />
                </LemonField>
            </div>
        </Form>
    )
}

function PublicLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { queryParams } = useValues(logic)

    return (
        <>
            <h3>External Link</h3>

            <p>
                You can also share or embed the recording outside of PostHog. Be aware that all the content of the
                recording will be accessible to anyone with the link.
            </p>

            <TimestampForm {...props} />
            <SharingModalContent recordingId={props.id} previewIframe additionalParams={queryParams} />
        </>
    )
}

function PrivateLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { url } = useValues(logic)

    return (
        <>
            <h3>Private Link</h3>
            <p>
                <b>Click the button below</b> to copy a direct link to this recording. Make sure the person you share it
                with has access to this PostHog project.
            </p>
            <LemonButton
                type="secondary"
                fullWidth
                center
                sideIcon={<IconCopy />}
                onClick={() => void copyToClipboard(url, url).then(captureException)}
                title={url}
            >
                <span className="truncate">{url}</span>
            </LemonButton>
            <TimestampForm {...props} />
        </>
    )
}

function LinearLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { shareUrl } = useValues(logic)
    const { setShareUrlValue, submitShareUrl } = useActions(logic)

    return (
        <Form logic={playerShareLogic} props={props} formKey="linearUrl">
            <h3>Share to Linear</h3>
            <p>
                <b>Click the button below</b> to start creating a new issue in Linear with a link to this recording.
            </p>

            <LemonField name="issueTitle" label="Issue title">
                <LemonInput placeholder="Issue title" fullWidth />
            </LemonField>
            <LemonField name="issueDescription" label="Issue description">
                <LemonTextArea placeholder="Issue description" />
            </LemonField>
            <div className="flex gap-2 items-center">
                <LemonField name="includeTime">
                    <LemonCheckbox label="Start at" />
                </LemonField>
                <LemonField name="time" inline>
                    <LemonInput
                        className={clsx('w-20', { 'opacity-50': !shareUrl.includeTime })}
                        placeholder="00:00"
                        onFocus={() => setShareUrlValue('includeTime', true)}
                        onBlur={() => submitShareUrl()}
                        fullWidth={false}
                        size="small"
                    />
                </LemonField>
            </div>
            <LemonButton
                type="primary"
                to={`https://linear.app/new?title=${encodeURIComponent(
                    shareUrl.issueTitle
                )}&description=${encodeURIComponent(shareUrl.issueDescription)}&url=${encodeURIComponent(
                    shareUrl.url
                )}`}
            >
                Create issue
            </LemonButton>
        </Form>
    )
}

export function PlayerShareRecording(props: PlayerShareLogicProps): JSX.Element {
    return (
        <div className="space-y-2">
            {props.shareType === 'private' && <PrivateLink {...props} />}

            {props.shareType === 'public' && <PublicLink {...props} />}

            {props.shareType === 'linear' && <LinearLink {...props} />}
        </div>
    )
}

export function openPlayerShareDialog(props: PlayerShareLogicProps): void {
    LemonDialog.open({
        title: 'Share recording',
        content: <PlayerShareRecording {...props} />,
        width: 600,
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
        zIndex: '1062',
    })
}
