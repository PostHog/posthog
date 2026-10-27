import { LemonModal, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { SaveAsChooserProps } from './saveAsTargets'

export function SaveAsModal({ isOpen, targets, onClose, onSelect }: SaveAsChooserProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Save query as"
            description="Choose what you want to create from this query."
            width={640}
            forceAbovePopovers
            data-attr="sql-editor-save-as-modal"
        >
            <div className="@container/save-as-modal">
                <div className="grid grid-cols-1 gap-2 @min-[36rem]/save-as-modal:grid-cols-2">
                    {targets.map((target) => {
                        const Icon = target.icon
                        const isDisabled = !!target.disabledReason

                        return (
                            <button
                                key={target.id}
                                type="button"
                                aria-disabled={isDisabled}
                                onClick={() => !isDisabled && onSelect(target.id)}
                                data-attr={target.dataAttr}
                                className={cn(
                                    'flex min-w-0 items-start gap-3 rounded border border-primary bg-surface-primary p-4 text-left',
                                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                                    isDisabled
                                        ? 'cursor-not-allowed'
                                        : 'cursor-pointer hover:border-accent hover:bg-fill-highlight-secondary'
                                )}
                            >
                                <Icon className="mt-0.5 shrink-0 text-xl text-secondary" />
                                <span className="flex min-w-0 flex-1 flex-col gap-1">
                                    <span className="flex flex-wrap items-center gap-2">
                                        <span className="font-semibold text-default">{target.label}</span>
                                        {target.recommended ? <LemonTag>Recommended</LemonTag> : null}
                                    </span>
                                    <span className="text-sm text-secondary">{target.description}</span>
                                    {target.disabledReason ? (
                                        <span className="text-xs text-warning">{target.disabledReason}</span>
                                    ) : null}
                                </span>
                            </button>
                        )
                    })}
                </div>
            </div>
        </LemonModal>
    )
}
