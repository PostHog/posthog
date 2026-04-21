import { useActions } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export type DashboardAiPromptChip = {
    id: string
    label: string
    prompt: string
}

export type DashboardAiPromptChipsProps = {
    chips: readonly DashboardAiPromptChip[]
    dashboardId?: number
    chipDisabledReason?: string | null
    onOpenAiWithPrompt: (prompt: string) => void
    dataAttrPrefix: string
    className?: string
    maxChips?: number
    /** Defaults to empty-dashboard copy. */
    description?: string
}

export function DashboardAiPromptChips({
    chips: chipsProp,
    dashboardId,
    chipDisabledReason,
    onOpenAiWithPrompt,
    dataAttrPrefix,
    className,
    maxChips,
    description = 'Pick a topic below. PostHog AI does the work so you can look at the data you care about quickly.',
}: DashboardAiPromptChipsProps): JSX.Element {
    const { reportDashboardEmptyAiPromptClicked } = useActions(eventUsageLogic)

    const chips = typeof maxChips === 'number' && maxChips >= 0 ? chipsProp.slice(0, maxChips) : chipsProp

    return (
        <div className={className}>
            <div className="rounded-xl border-2 border-[var(--color-ai)] bg-bg-surface-primary p-4">
                <div className="flex items-center gap-2 mb-1">
                    <IconSparkles className="text-ai size-4 shrink-0" />
                    <span className="text-sm font-semibold">Try PostHog AI</span>
                </div>
                <p className="text-sm text-secondary m-0 mb-3">{description}</p>
                <div className="flex flex-wrap gap-2">
                    {chips.map((chip) => {
                        const button = (
                            <LemonButton
                                type="secondary"
                                size="small"
                                className="max-w-full whitespace-normal text-left [&_.LemonButton__chrome]:h-auto [&_.LemonButton__chrome]:py-1.5"
                                disabledReason={chipDisabledReason || undefined}
                                data-attr={`${dataAttrPrefix}-${chip.id}`}
                                onClick={() => {
                                    reportDashboardEmptyAiPromptClicked(chip.label, dashboardId)
                                    onOpenAiWithPrompt(chip.prompt)
                                }}
                            >
                                {chip.label}
                            </LemonButton>
                        )
                        return (
                            <Tooltip key={chip.id} title={chipDisabledReason ? chipDisabledReason : chip.prompt}>
                                {button}
                            </Tooltip>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
