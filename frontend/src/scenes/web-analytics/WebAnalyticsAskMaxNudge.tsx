import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { webAnalyticsAskMaxNudgeLogic } from 'scenes/web-analytics/webAnalyticsAskMaxNudgeLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

const MAX_PROMPT =
    '!Summarize the key insights in my web analytics for the selected period and point out anything notable.'

export function WebAnalyticsAskMaxNudge(): JSX.Element | null {
    const { promptVisible } = useValues(webAnalyticsAskMaxNudgeLogic)
    const { dismissNudge, nudgeClicked } = useActions(webAnalyticsAskMaxNudgeLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    if (!promptVisible) {
        return null
    }

    const askMax = (): void => {
        nudgeClicked()
        openSidePanel(SidePanelTab.Max, MAX_PROMPT)
    }

    return (
        <div
            className="animate-slide-in-up z-top fixed bottom-6 right-6 flex h-fit w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-lg border bg-surface-primary p-4 shadow-lg"
            data-attr="web-analytics-ask-max-nudge"
        >
            <div className="flex items-start justify-between gap-2">
                <h4 className="m-0 text-base font-semibold">Not sure where to start?</h4>
                <LemonButton size="xsmall" icon={<IconX />} tooltip="Dismiss" onClick={dismissNudge} />
            </div>
            <p className="m-0 text-sm text-muted">
                PostHog AI can explain any metric or pull the answer you’re looking for. Just ask.
            </p>
            <LemonButton className="self-start" type="primary" icon={<IconSparkles />} onClick={askMax}>
                Ask PostHog AI
            </LemonButton>
        </div>
    )
}
