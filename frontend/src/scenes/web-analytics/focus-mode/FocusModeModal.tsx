import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { cn } from 'lib/utils/css-classes'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { CONCERN_ICONS, CONCERN_LABELS, CONCERN_ORDER, WebAnalyticsConcern } from './types'

export function FocusModeModal(): JSX.Element {
    const { focusModeModalOpen, focusModeDraftConcerns } = useValues(webAnalyticsLogic)
    const { closeFocusModeModal, toggleFocusModeConcern, applyFocusMode } = useActions(webAnalyticsLogic)
    const canApply = focusModeDraftConcerns.length > 0

    return (
        <LemonModal
            isOpen={focusModeModalOpen}
            onClose={closeFocusModeModal}
            title="Focus mode"
            description="Choose the areas you want to keep visible."
            footer={
                <div className="flex justify-end w-full gap-2">
                    <LemonButton type="secondary" onClick={closeFocusModeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={applyFocusMode}
                        disabledReason={canApply ? undefined : 'Choose at least one area'}
                        data-attr="focus-mode-apply"
                    >
                        Save and apply
                    </LemonButton>
                </div>
            }
        >
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {CONCERN_ORDER.map((concern) => (
                    <SelectableConcern
                        key={concern}
                        concern={concern}
                        selected={focusModeDraftConcerns.includes(concern)}
                        onClick={() => toggleFocusModeConcern(concern)}
                    />
                ))}
            </div>
        </LemonModal>
    )
}

interface SelectableConcernProps {
    concern: WebAnalyticsConcern
    selected: boolean
    onClick: () => void
}

function SelectableConcern({ concern, selected, onClick }: SelectableConcernProps): JSX.Element {
    const Icon = CONCERN_ICONS[concern]

    return (
        <button
            type="button"
            aria-pressed={selected}
            aria-label={CONCERN_LABELS[concern]}
            onClick={onClick}
            data-attr={`focus-mode-concern-${concern}`}
            className={cn(
                'group relative flex min-h-24 flex-col items-center gap-2 rounded border-2 p-3 text-center transition-colors',
                'cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                selected
                    ? 'border-accent bg-accent-highlight-secondary'
                    : 'border-border-primary bg-surface-primary hover:border-accent/40 hover:bg-surface-secondary'
            )}
        >
            <Icon
                fontSize={32}
                className={cn('shrink-0', selected ? 'text-accent' : 'text-secondary group-hover:text-primary')}
            />
            <div className="text-sm font-semibold leading-tight">{CONCERN_LABELS[concern]}</div>
        </button>
    )
}
