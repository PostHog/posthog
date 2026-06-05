import { LemonButton } from '@posthog/lemon-ui'

import type { WidgetAvailabilityConfig } from '../../widget_types/widgetAvailability'
import { WIDGET_AVAILABILITY_PRESENTATION } from '../../widget_types/widgetAvailability'
import { WidgetCardContent } from '../WidgetCard/WidgetCardBody'
import { WidgetCardProductIntroduction } from '../WidgetCardProductIntroduction/WidgetCardProductIntroduction'

type WidgetAvailabilitySetupPromptProps = {
    availability: WidgetAvailabilityConfig
    className?: string
}

export function WidgetAvailabilitySetupPrompt({
    availability,
    className,
}: WidgetAvailabilitySetupPromptProps): JSX.Element {
    const presentation = WIDGET_AVAILABILITY_PRESENTATION[availability.requirement]

    return (
        <WidgetCardContent className={className}>
            <WidgetCardProductIntroduction
                stacked
                className="border-none mb-0 mt-0 p-4"
                productName={presentation.productName}
                productKey={presentation.productKey}
                thingName={presentation.thingName}
                titleOverride={availability.unavailableTitle}
                description={availability.unavailableReason}
                isEmpty
                docsURL={availability.docsHref}
                actionElementOverride={
                    <div className="flex flex-col items-center gap-4">
                        <LemonButton type="primary" to={presentation.settingsUrl}>
                            {availability.setupActionLabel}
                        </LemonButton>
                    </div>
                }
            />
        </WidgetCardContent>
    )
}
