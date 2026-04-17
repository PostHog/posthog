import { useActions } from 'kea'

import { IconArrowRight, IconSparkles } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

export function AskMaxCard(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { trackCardClick, closeDialog } = useActions(welcomeDialogLogic)

    return (
        <LemonCard
            hoverEffect={false}
            className="p-4 cursor-pointer hover:bg-accent-highlight-secondary transition-colors"
            onClick={() => {
                trackCardClick('next_steps', 'sidepanel:max')
                closeDialog()
                openSidePanel(SidePanelTab.Max)
            }}
            data-attr="welcome-ask-max"
        >
            <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-[var(--color-brand-yellow)]/15 flex items-center justify-center text-[var(--color-brand-yellow)]">
                    <IconSparkles className="text-xl" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm">Got questions? Ask Max, PostHog AI</div>
                    <div className="text-xs text-muted">Find anything in your data or ask how to use a feature</div>
                </div>
                <IconArrowRight className="text-muted text-lg flex-shrink-0" />
            </div>
        </LemonCard>
    )
}
