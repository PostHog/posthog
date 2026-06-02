import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { CONCERN_ICONS, CONCERN_ORDER } from './types'

export function FocusModeOnboardingModal(): JSX.Element {
    const { focusModeOnboardingModalOpen } = useValues(webAnalyticsLogic)
    const { startFocusModeOnboarding, dismissFocusModeOnboarding } = useActions(webAnalyticsLogic)

    return (
        <LemonModal
            isOpen={focusModeOnboardingModalOpen}
            onClose={dismissFocusModeOnboarding}
            title="Meet focus mode"
            width={520}
            footer={
                <div className="flex justify-end w-full gap-2">
                    <LemonButton type="secondary" onClick={dismissFocusModeOnboarding}>
                        Skip for now
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={startFocusModeOnboarding}
                        data-attr="focus-mode-onboarding-start"
                    >
                        Set up focus mode
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <p className="m-0">
                    Focus mode lets you tailor Web Analytics around what matters most. Surface the metrics you care
                    about, while keeping everything else within reach.
                </p>
                <div className="flex flex-wrap justify-center gap-3 rounded bg-surface-secondary p-3">
                    {CONCERN_ORDER.map((concern) => {
                        const Icon = CONCERN_ICONS[concern]
                        return <Icon key={concern} fontSize={28} className="text-secondary" />
                    })}
                </div>
                <p className="m-0 text-sm text-secondary">
                    Focus mode is personal to you. Your teammates will continue to see their own views, and you can
                    toggle it on or off whenever you'd like.
                </p>
            </div>
        </LemonModal>
    )
}
