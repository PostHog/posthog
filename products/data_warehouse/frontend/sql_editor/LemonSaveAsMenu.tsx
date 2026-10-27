import { IconInfo } from '@posthog/icons'
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
            disabledReason: target.disabledReason,
            tooltip: target.helpText,
            'data-attr': target.dataAttr,
            sideAction: {
                icon: <IconInfo />,
                to: target.docsUrl,
                targetBlank: true,
                tooltip: target.helpText,
                'aria-label': `Learn more about ${target.label.toLowerCase()}`,
                'data-attr': `sql-editor-save-as-${target.id}-help`,
            },
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
        <div className="w-80" data-attr="sql-editor-save-as-modal">
            <LemonMenuOverlay items={items} tooltipPlacement="left" />
        </div>
    )
}
