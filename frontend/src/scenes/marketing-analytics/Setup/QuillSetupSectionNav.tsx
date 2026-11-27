import { Badge, Button } from '@posthog/quill'

import { QuillOptionSelect } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/common/QuillOptionSelect'
import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { suggestionsForSection } from './sectionRouting'

export function QuillSetupSectionNav({
    sections,
    activeKey,
    suggestions,
    onSelect,
}: {
    sections: { key: SetupSection; label: string }[]
    activeKey: SetupSection
    suggestions: Suggestion[]
    onSelect: (section: SetupSection) => void
}): JSX.Element {
    return (
        <>
            <div className="@min-[48rem]/main-content:hidden">
                <QuillOptionSelect
                    value={activeKey}
                    onChange={onSelect}
                    options={sections.map(({ key, label }) => ({ value: key, label }))}
                    ariaLabel="Setup section"
                    className="w-full"
                />
            </div>
            <nav className="hidden @min-[48rem]/main-content:flex w-56 shrink-0 flex-col gap-px">
                {sections.map((section) => {
                    const forSection = suggestionsForSection(suggestions, section.key)
                    const hasError = forSection.some((suggestion) => suggestion.severity === 'error')
                    const active = section.key === activeKey
                    return (
                        <Button
                            key={section.key}
                            left
                            aria-current={active ? 'page' : undefined}
                            className={active ? 'w-full bg-fill-selected' : 'w-full'}
                            onClick={() => onSelect(section.key)}
                        >
                            <span className="min-w-0 flex-1 truncate text-left">{section.label}</span>
                            {forSection.length > 0 && (
                                <Badge variant={hasError ? 'destructive' : 'warning'}>{forSection.length}</Badge>
                            )}
                        </Button>
                    )
                })}
            </nav>
        </>
    )
}
