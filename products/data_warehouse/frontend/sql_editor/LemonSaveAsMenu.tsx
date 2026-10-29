import { LemonTag } from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import type { LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import type { SaveAsMenuProps } from './saveAsTargets'

export interface LemonSaveAsMenuContentProps extends SaveAsMenuProps {
    beforeItems?: LemonMenuItem[]
    afterItemSections?: LemonMenuItem[][]
}

export function getLemonSaveAsTargetMenuItems({ targets, onSelect }: SaveAsMenuProps): LemonMenuItem[] {
    return targets.map((target) => {
        const Icon = target.icon

        return {
            key: target.id,
            icon: <Icon className="text-lg" />,
            label: (
                <span className="flex min-w-0 flex-1 flex-col items-start gap-0.5 py-1 text-left">
                    <span className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-default">{target.label}</span>
                        {target.recommended ? <LemonTag size="small">Recommended</LemonTag> : null}
                    </span>
                    <span className="text-xs font-normal text-secondary">{target.description}</span>
                    {target.disabledReason ? (
                        <span className="text-xs font-normal text-warning">{target.disabledReason}</span>
                    ) : null}
                </span>
            ),
            onClick: () => onSelect(target.id),
            // The label already shows the disabled reason, so the tooltip keeps only the help text.
            disabled: !!target.disabledReason,
            tooltip: target.helpText,
            tooltipDocLink: target.docsUrl,
            'data-attr': target.dataAttr,
        }
    })
}

export function LemonSaveAsMenuContent({
    targets,
    onSelect,
    beforeItems = [],
    afterItemSections = [],
}: LemonSaveAsMenuContentProps): JSX.Element {
    const items: LemonMenuItems = [
        ...(beforeItems.length ? [{ items: beforeItems }] : []),
        { title: 'Save query as', items: getLemonSaveAsTargetMenuItems({ targets, onSelect }) },
        ...afterItemSections.map((items) => ({ items })),
    ]

    return (
        <div className="min-w-0" data-attr="sql-editor-save-as-modal">
            <LemonMenuOverlay items={items} tooltipPlacement="left" />
        </div>
    )
}
