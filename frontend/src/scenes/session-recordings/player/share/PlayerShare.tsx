import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

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
        <>
            <p>
                <b>Click the button below</b> to copy a direct link to this recording. Make sure the person you share it
                with has access to this PostHog project.
            </p>
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
                <span className="truncate">{privateLinkUrl}</span>
            </LemonButton>
            <TimestampForm {...props} />
        </>
    )
}

function LinearLink(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { linearLinkForm, linearUrl, linearLinkFormHasErrors } = useValues(logic)
    const { setLinearLinkFormValue } = useActions(logic)

    return (
        <>
            <p>Add an issue to your Linear workspace with a link to this recording.</p>

            <Form logic={playerShareLogic} props={props} formKey="linearLinkForm" className="flex flex-col gap-2">
                <LemonField className="gap-1" name="issueTitle" label="Issue title">
                    <LemonInput fullWidth />
                </LemonField>
                <LemonField
                    className="gap-1"
                    name="issueDescription"
                    label="Issue description"
                    help={<span>We'll include a link to the recording in the description.</span>}
                >
                    <LemonTextArea />
                </LemonField>
                <div className="flex gap-1 items-center">
                    <LemonField name="includeTime">
                        <LemonCheckbox label="Start at" checked={linearLinkForm.includeTime} />
                    </LemonField>
                    <LemonField name="time" inline>
                        <LemonInput
                            className={clsx('w-20', { 'opacity-50': !linearLinkForm.includeTime })}
                            onFocus={() => setLinearLinkFormValue('includeTime', true)}
                            placeholder="00:00"
                            fullWidth={false}
                            size="small"
                        />
                    </LemonField>
                </div>
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        to={linearUrl}
                        targetBlank={true}
                        disabledReason={linearLinkFormHasErrors ? 'Fix all errors before continuing' : undefined}
                    >
                        Create issue
                    </LemonButton>
                </div>
            </Form>
        </>
    )
}

export function PlayerShareRecording(props: PlayerShareLogicProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            {props.shareType === 'private' && <PrivateLink {...props} />}

            {props.shareType === 'public' && <PublicLink {...props} />}

            {props.shareType === 'linear' && <LinearLink {...props} />}
        </div>
    )
}

export function openPlayerShareDialog(props: PlayerShareLogicProps): void {
    LemonDialog.open({
        title:
            props.shareType === 'private'
                ? 'Share private link'
                : props.shareType === 'public'
                  ? 'Share public link'
                  : 'Share to Linear',
        content: <PlayerShareRecording {...props} />,
        width: 600,
        zIndex: '1162',
        primaryButton: null,
    })
}
