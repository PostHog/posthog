import { IconChevronDown } from '@posthog/icons'
import { LemonDropdown } from '@posthog/lemon-ui'

import { ProductKey } from '~/queries/schema/schema-general'

import { QuickstartToolStatus } from '../../quickstartLogic'
import { captureQuickstartAction } from '../captureQuickstartAction'
import { JourneyOverlay } from './JourneyOverlay'

export function JourneyMeter({
    status,
    productKey,
}: {
    status: QuickstartToolStatus
    productKey: ProductKey
}): JSX.Element {
    const achievedStepCount = status.journey.filter((step) => step.achieved).length

    return (
        <LemonDropdown
            overlay={<JourneyOverlay journey={status.journey} productKey={productKey} />}
            placement="bottom-end"
            onVisibilityChange={(visible) => visible && captureQuickstartAction('view_tool_journey', productKey)}
        >
            <button
                type="button"
                className="flex items-center gap-2 w-full p-0 border-0 bg-transparent cursor-pointer group"
                aria-label="Show setup details"
                data-attr={`quickstart-journey-${productKey}`}
            >
                <span className="flex items-center gap-1 flex-1">
                    {status.journey.map((step, index) => (
                        <span
                            key={step.key}
                            className={`h-1 flex-1 rounded-full transition-colors ${
                                index < achievedStepCount
                                    ? 'bg-success'
                                    : index === achievedStepCount && status.nextStep
                                      ? 'bg-accent'
                                      : 'bg-fill-tertiary'
                            }`}
                        />
                    ))}
                </span>
                <span className="text-xs text-tertiary group-hover:text-primary">Setup details</span>
                <IconChevronDown className="text-tertiary group-hover:text-primary" />
            </button>
        </LemonDropdown>
    )
}
