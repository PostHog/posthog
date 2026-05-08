import { useActions } from 'kea'

import { IconArrowRight, IconSparkles } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

export function AskMaxCard(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { trackCardClick, closeDialog } = useActions(welcomeDialogLogic)

    const handleActivate = (): void => {
        trackCardClick('next_steps', 'sidepanel:max')
        closeDialog()
        openSidePanel(SidePanelTab.Max)
    }

    return (
        <LemonCard
            hoverEffect={false}
            className="p-0 overflow-hidden"
            // LemonCard renders a plain <div>; we wrap the whole clickable area in a <button> inside it
            // so the card is reachable via Tab and activatable via Enter/Space.
        >
            <button
                type="button"
                onClick={handleActivate}
                data-attr="welcome-ask-max"
                className="flex items-center gap-3 w-full p-4 text-left bg-transparent border-0 cursor-pointer hover:bg-accent-highlight-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--color-brand-yellow)] transition-colors"
                aria-label="Got questions? Ask Max, PostHog AI"
            >
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-[var(--color-brand-yellow)]/15 flex items-center justify-center text-[var(--color-brand-yellow)]">
                    <IconSparkles className="text-xl" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm">Got questions? Ask Max, PostHog AI</div>
                    <div className="text-xs text-muted">Find anything in your data or ask how to use a feature</div>
                </div>
                <IconArrowRight className="text-muted text-lg flex-shrink-0" />
            </button>
        </LemonCard>
    )
}
