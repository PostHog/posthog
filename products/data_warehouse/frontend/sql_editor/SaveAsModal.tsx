import { IconInfo } from '@posthog/icons'
import { LemonModal, LemonTag, Tooltip as LemonTooltip } from '@posthog/lemon-ui'

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
                            <div
                                key={target.id}
                                className={cn(
                                    'flex min-w-0 rounded border border-primary bg-surface-primary',
                                    isDisabled ? 'bg-fill-highlight-secondary' : 'hover:border-accent'
                                )}
                            >
                                <button
                                    type="button"
                                    aria-disabled={isDisabled}
                                    onClick={() => !isDisabled && onSelect(target.id)}
                                    data-attr={target.dataAttr}
                                    className={cn(
                                        'flex min-w-0 flex-1 items-start gap-3 rounded p-4 text-left',
                                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                                        isDisabled
                                            ? 'cursor-not-allowed'
                                            : 'cursor-pointer hover:bg-fill-highlight-secondary'
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
                                <LemonTooltip
                                    title={target.helpText}
                                    docLink={target.docsUrl}
                                    openOnClick
                                    placement="left"
                                    containerClassName="max-w-64"
                                >
                                    <button
                                        type="button"
                                        aria-label={`About ${target.label.toLowerCase()}`}
                                        data-attr={`sql-editor-save-as-${target.id}-help`}
                                        className="m-2 flex size-7 shrink-0 cursor-help items-center justify-center rounded text-secondary hover:bg-fill-highlight-secondary hover:text-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                                    >
                                        <IconInfo />
                                    </button>
                                </LemonTooltip>
                            </div>
                        )
                    })}
                </div>
            </div>
        </LemonModal>
    )
}
