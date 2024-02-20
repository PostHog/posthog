import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { SharingModalContent } from 'lib/components/Sharing/SharingModal'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { playerShareLogic, PlayerShareLogicProps } from './playerShareLogic'

export function PlayerShareRecording(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { shareUrl, url, queryParams } = useValues(logic)
    const { setShareUrlValue, submitShareUrl } = useActions(logic)

    return (
        <div className="space-y-2">
            <h3>Internal Link</h3>
            <p>
                <b>Click the button below</b> to copy a direct link to this recording. Make sure the person you share it
                with has access to this PostHog project.
            </p>
            <LemonButton
                type="secondary"
                fullWidth
                center
                sideIcon={<IconCopy />}
                onClick={() => void copyToClipboard(url, 'recording link').then(captureException)}
                title={url}
            >
                <span className="truncate">{url}</span>
            </LemonButton>

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

            <LemonDivider className="my-4" />

            <h3>External Link</h3>

            <p>
                You can also share or embed the recording outside of PostHog. Be aware that all the content of the
                recording will be accessible to anyone with the link.
            </p>

            <SharingModalContent recordingId={props.id} previewIframe additionalParams={queryParams} />
        </div>
    )
}

export function openPlayerShareDialog({ seconds, id }: PlayerShareLogicProps): void {
    LemonDialog.open({
        title: 'Share recording',
        content: <PlayerShareRecording seconds={seconds} id={id} />,
        width: 600,
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
    })
}
