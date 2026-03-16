import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'

import { SharingModalContent } from 'lib/components/Sharing/SharingModal'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { PlayerShareLogicProps, playerShareLogic } from './playerShareLogic'

function TimestampForm(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { privateLinkForm } = useValues(logic)
    const { setPrivateLinkFormValue } = useActions(logic)

    return (
        <Form logic={playerShareLogic} props={props} formKey="privateLinkForm">
            <div className="flex gap-2 items-center">
                <LemonField name="includeTime">
                    <LemonCheckbox label="Start at" checked={privateLinkForm.includeTime} />
                </LemonField>
                <LemonField name="time" inline>
                    <LemonInput
                        className={clsx('w-20', { 'opacity-50': !privateLinkForm.includeTime })}
                        placeholder="00:00"
                        onFocus={() => setPrivateLinkFormValue('includeTime', true)}
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

    const { privateLinkUrlQueryParams } = useValues(logic)

    return (
        <>
            <p>
                You can share or embed the recording outside of PostHog. Be aware that all the content of the recording
                will be accessible to anyone with the link.
            </p>

            <SharingModalContent
                recordingId={props.id}
                previewIframe
                additionalParams={privateLinkUrlQueryParams}
                recordingLinkTimeForm={<TimestampForm {...props} />}
            />
        </>
    )
}

function PrivateLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { privateLinkUrl, privateLinkFormHasErrors } = useValues(logic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <div>
                    <b>Click the button below</b> to copy a direct link to this recording.
                </div>
                <div>Make sure the person you share it with has access to this PostHog project.</div>
            </div>
            <LemonButton
                type="secondary"
                fullWidth
                center
                sideIcon={<IconCopy />}
                onClick={() =>
                    void copyToClipboard(privateLinkUrl, privateLinkUrl).catch((e) => posthog.captureException(e))
                }
                title={privateLinkUrl}
                disabledReason={privateLinkFormHasErrors ? 'Fix all errors before continuing' : undefined}
            >
                <span className="break-all">{privateLinkUrl}</span>
            </LemonButton>
            <TimestampForm {...props} />
        </div>
    )
}

export function PlayerShareRecording({
    ...props
}: PlayerShareLogicProps & { onCloseDialog?: () => void }): JSX.Element {
    return (
        <div className="gap-y-2">
            {props.shareType === 'private' && <PrivateLink {...props} />}

            {props.shareType === 'public' && <PublicLink {...props} />}
        </div>
    )
}

const shareTitleMapping = {
    private: 'Share private link',
    public: 'Share public link',
}

export function openPlayerShareDialog(props: PlayerShareLogicProps): void {
    LemonDialog.open({
        title: props.shareType ? shareTitleMapping[props.shareType] : '',
        content: (closeDialog) => <PlayerShareRecording {...props} onCloseDialog={closeDialog} />,
        maxWidth: '85vw',
        zIndex: '1162',
        primaryButton: null,
    })
}
