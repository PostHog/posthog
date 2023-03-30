import { LemonCollapse, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PureField } from 'lib/forms/Field'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { automationStepConfigLogic } from '../automationStepConfigLogic'

export function SlackDestinationConfig(): JSX.Element {
    const { activeStep, exampleEvent, previewPayload } = useValues(automationStepConfigLogic)
    const { updateActiveStep, setExampleEvent } = useActions(automationStepConfigLogic)

    return (
        <>
            <PureField label={'Select the slack channel'}>
                <LemonInput
                    placeholder="#general"
                    value={activeStep?.data?.channel}
                    onChange={(channel) => {
                        updateActiveStep(activeStep?.data?.id, { channel })
                    }}
                />
            </PureField>
            <div className="mt-4" />
            <PureField label={'Message'} className="max-w-160">
                <JSONEditorInput
                    defaultNumberOfLines={4}
                    value={activeStep?.data?.payload}
                    onChange={(payload) => {
                        updateActiveStep(activeStep?.data?.id, { payload })
                    }}
                />
            </PureField>
            <div className="mt-4" />
            <PureField label={'Preview'} className="max-w-160">
                <JSONEditorInput defaultNumberOfLines={4} value={JSON.stringify(previewPayload, null, 4)} readOnly />
                <LemonCollapse
                    panels={[
                        {
                            key: '1',
                            header: <span>Example event</span>,
                            content: (
                                <JSONEditorInput
                                    defaultNumberOfLines={4}
                                    value={exampleEvent}
                                    onChange={(val) => {
                                        setExampleEvent(val)
                                    }}
                                />
                            ),
                        },
                    ]}
                />
            </PureField>
            <div className="mt-4" />
        </>
    )
}
