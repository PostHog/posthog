import { useActions } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { customerAnalyticsDashboardEventsLogic } from '../scenes/CustomerAnalyticsConfigurationScene/events/customerAnalyticsDashboardEventsLogic'

type ConfigureWithAIButtonProps = LemonButtonProps & {
    prompt: string
    event?: string
    eventToHighlight?: string
    children?: React.ReactNode
}

export function ConfigureWithAIButton({
    prompt,
    event,
    eventToHighlight,
    children,
    ...props
}: ConfigureWithAIButtonProps): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { addEventToHighlight } = useActions(customerAnalyticsDashboardEventsLogic)
    const { reportCustomerAnalyticsDashboardConfigureEventWithAIClicked } = useActions(eventUsageLogic)

    const handleClick = (): void => {
        openSidePanel(SidePanelTab.Max, prompt)
        if (eventToHighlight) {
            addEventToHighlight(eventToHighlight)
        }
        reportCustomerAnalyticsDashboardConfigureEventWithAIClicked({ event: event || eventToHighlight })
    }

    return (
        <LemonButton
            size="small"
            type="tertiary"
            icon={<IconSparkles className="text-accent" />}
            tooltip="Configure with PostHog AI"
            onClick={handleClick}
            className="border border-accent border-dashed p-1"
            data-attr="customer-analytics-configure-event-with-ai"
            noPadding
            {...props}
        >
            {children}
        </LemonButton>
    )
}
