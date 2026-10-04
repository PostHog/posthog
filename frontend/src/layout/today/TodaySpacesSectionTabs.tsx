import { ReactNode } from 'react'

import { Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { TodayWorkSectionId } from './todaySpacesLogic'

const SECTIONS: { id: TodayWorkSectionId; label: string }[] = [
    { id: 'pinned', label: 'Pinned' },
    { id: 'recent', label: 'Recent' },
    { id: 'spaces', label: 'Spaces' },
]

interface TodaySpacesSectionTabsProps {
    value: TodayWorkSectionId
    onChange: (section: TodayWorkSectionId) => void
    counts: Partial<Record<TodayWorkSectionId, number>>
    actions?: ReactNode
}

export function TodaySpacesSectionTabs({ value, onChange, counts, actions }: TodaySpacesSectionTabsProps): JSX.Element {
    return (
        <div className="sticky top-0 z-10 -mx-3 mb-1 flex items-center border-b border-border bg-[var(--today-paper)] px-3">
            <Tabs
                value={value}
                onValueChange={(next) => onChange(next as TodayWorkSectionId)}
                className="min-w-0 flex-1"
            >
                <TabsList variant="line" className="!h-11 gap-4 !p-0">
                    {SECTIONS.map(({ id, label }) => (
                        <TabsTrigger
                            key={id}
                            value={id}
                            className="h-11 !px-0 text-xxs font-semibold tracking-wider uppercase"
                            data-attr={`today-spaces-tab-${id}`}
                        >
                            {label}
                            {counts[id] ? (
                                <span className="font-normal tracking-normal text-muted-foreground tabular-nums">
                                    {counts[id]}
                                </span>
                            ) : null}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>
            {actions && <div className="flex shrink-0 items-center">{actions}</div>}
        </div>
    )
}
