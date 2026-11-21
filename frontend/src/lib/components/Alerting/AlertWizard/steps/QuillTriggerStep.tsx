import { useActions, useValues } from 'kea'

import { CardGroup, Heading, Text } from '@posthog/quill'

import { WizardTrigger, alertWizardLogic } from '../alertWizardLogic'
import { QuillWizardCard } from './QuillWizardCard'

export function QuillTriggerStep(): JSX.Element {
    const { availableTriggers } = useValues(alertWizardLogic)
    const { setTriggerKey } = useActions(alertWizardLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    What should trigger the alert?
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Choose when you want to be notified
                </Text>
            </div>

            <CardGroup size="sm">
                {availableTriggers.map((trigger: WizardTrigger) => (
                    <QuillWizardCard
                        key={trigger.key}
                        name={trigger.name}
                        description={trigger.description}
                        onClick={() => setTriggerKey(trigger.key)}
                    />
                ))}
            </CardGroup>
        </div>
    )
}
