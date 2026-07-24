import { useActions } from 'kea'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ProductKey } from '~/queries/schema/schema-general'

import { QuickstartJourneyStep, quickstartLogic } from '../../quickstartLogic'
import { captureQuickstartAction } from '../captureQuickstartAction'

export function JourneyOverlay({
    journey,
    productKey,
}: {
    journey: QuickstartJourneyStep[]
    productKey: ProductKey
}): JSX.Element {
    const { openTaskGuidance } = useActions(quickstartLogic)
    const sections = [
        { title: 'Get it live', steps: journey.filter((step) => step.kind === 'activation') },
        { title: 'Improve quality', steps: journey.filter((step) => step.kind === 'quality') },
    ].filter((section) => section.steps.length > 0)

    return (
        <div className="p-2 max-w-100 flex flex-col gap-3">
            {sections.map((section) => (
                <div key={section.title}>
                    <div className="text-xs font-semibold text-secondary mb-1">{section.title}</div>
                    <ul className="flex flex-col gap-1 mb-0">
                        {section.steps.map((step) => (
                            <li key={step.key}>
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    fullWidth
                                    center={false}
                                    icon={
                                        step.achieved ? (
                                            <IconCheckCircle className="text-success" />
                                        ) : (
                                            <span className="w-3 h-3 rounded-full border-2 border-current text-muted-alt" />
                                        )
                                    }
                                    sideIcon={<IconArrowRight />}
                                    onClick={() => {
                                        captureQuickstartAction('open_tool_task', productKey, { step_key: step.key })
                                        openTaskGuidance(productKey, step.key)
                                    }}
                                    data-attr={`quickstart-task-${productKey}-${step.key}`}
                                >
                                    <span
                                        className={`whitespace-normal text-left ${step.achieved ? 'text-tertiary' : ''}`}
                                    >
                                        {step.label}
                                    </span>
                                </LemonButton>
                            </li>
                        ))}
                    </ul>
                </div>
            ))}
        </div>
    )
}
