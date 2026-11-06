import './TodayShell.scss'

import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { TodayPaneList } from './TodayPaneList'
import { TodayPaneSection } from './TodayPaneSection'
import { peopleRecentRowKey } from './todayPeople'
import { TodayPeopleRow, TodayPeopleRowCounts, TodayPeopleRowKey, todayPeopleLogic } from './todayPeopleLogic'
import { TodayPeopleNavRow } from './TodayPeopleNavRow'
import { TodayPeopleRecentRow } from './TodayPeopleRecentRow'

function rowMeta(key: TodayPeopleRowKey, counts: TodayPeopleRowCounts): string | undefined {
    const count = counts[key as keyof TodayPeopleRowCounts]
    return count === undefined ? undefined : humanFriendlyLargeNumber(count)
}

export function TodayPeopleSidebar(): JSX.Element {
    const { primaryRows, moreRows, hasMoreRows, moreOpen, counts, recentRows, activeRow, collapsedSections } =
        useValues(todayPeopleLogic)
    const { toggleSection, toggleMore } = useActions(todayPeopleLogic)

    const renderRow = (row: TodayPeopleRow): JSX.Element => (
        <TodayPeopleNavRow key={row.key} row={row} meta={rowMeta(row.key, counts)} active={activeRow === row.key} />
    )

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <TodayPaneList>
                <div className="flex flex-col gap-px pb-2">
                    {primaryRows.map(renderRow)}
                    {moreRows.map(renderRow)}
                    {hasMoreRows && (
                        <Button
                            size="row"
                            left
                            className="w-full min-w-0 text-muted-foreground"
                            aria-expanded={moreOpen}
                            onClick={toggleMore}
                            data-attr="people-sidebar-see-more"
                        >
                            <IconChevronDown className={cn('size-4 shrink-0', moreOpen && 'rotate-180')} />
                            {moreOpen ? 'See less' : 'See more'}
                        </Button>
                    )}
                </div>
                {recentRows.length > 0 && (
                    <TodayPaneSection
                        label="Recents"
                        open={!collapsedSections.includes('recents')}
                        count={recentRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('recents')}
                        divider
                        dataAttr="people-section-recents"
                    >
                        {recentRows.map((recent) => (
                            <TodayPeopleRecentRow
                                key={recent.href}
                                recent={recent}
                                active={activeRow === peopleRecentRowKey(recent.href)}
                            />
                        ))}
                    </TodayPaneSection>
                )}
            </TodayPaneList>
        </div>
    )
}
