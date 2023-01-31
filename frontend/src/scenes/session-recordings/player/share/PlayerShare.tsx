import { LemonButton, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconCopy } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Field } from 'lib/forms/Field'
import { copyToClipboard } from 'lib/utils'
import { playerShareLogic, PlayerShareLogicProps } from './playerShareLogic'

export function ShareRecording(props: PlayerShareLogicProps): JSX.Element {
    const logic = playerShareLogic(props)

    const { shareUrl, url } = useValues(logic)
    const { setShareUrlValue, submitShareUrl } = useActions(logic)

    return (
        <div className="space-y-2">
            <p>
                <b>Click the button below</b> to copy a direct link to this recording. Make sure the person you share it
                with has access to this PostHog project.
            </p>
            <LemonButton
                type="secondary"
                fullWidth
                center
                sideIcon={<IconCopy />}
                onClick={() => copyToClipboard(url, 'recording link')}
                title={url}
            >
                <span className="truncate">{url}</span>
            </LemonButton>

            <Form logic={playerShareLogic} props={props} formKey="shareUrl">
                <div className="flex gap-2 items-center">
                    <Field name="includeTime">
                        <LemonCheckbox label="Start at" />
                    </Field>
                    <Field name="time" inline>
                        <LemonInput
                            className={clsx('w-20', { 'opacity-50': !shareUrl.includeTime })}
                            placeholder="00:00"
                            onFocus={() => setShareUrlValue('includeTime', true)}
                            onBlur={() => submitShareUrl()}
                            fullWidth={false}
                        />
                    </Field>
                </div>
            </Form>
        </div>
    )
}

export function openPlayerShareDialog({ seconds, id }: PlayerShareLogicProps): void {
    LemonDialog.open({
        title: 'Share recording',
        content: <ShareRecording seconds={seconds} id={id} />,
        width: 600,
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
    })
}
