import './TodayShell.scss'

import { useActions, useValues } from 'kea'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { customNavCountRegistry } from '~/layout/panel-layout/ProjectTree/customIconRegistry'
import { SidebarRowEnter } from '~/layout/today/sidebar/SidebarRowEnter'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { SidebarSection } from '~/layout/today/sidebar/SidebarSection'

import { peopleRecentRowKey } from './todayPeople'
import { TodayPeopleRow, TodayPeopleRowKey, todayPeopleLogic } from './todayPeopleLogic'
import { TodayPeopleNavRow } from './TodayPeopleNavRow'
import { TodayPeopleRecentRow } from './TodayPeopleRecentRow'

function rowMeta(key: TodayPeopleRowKey, counts: Partial<Record<TodayPeopleRowKey, number>>): string | undefined {
    const count = counts[key]
    return count === undefined ? undefined : humanFriendlyLargeNumber(count)
}

export function TodayPeopleSidebar(): JSX.Element {
    const {
        topRows,
        rowSections,
        counts,
        matchingPinnedRows,
        matchingRecentRows,
        activeRow,
        isSectionOpen,
        isSearching,
        searchQuery,
    } = useValues(todayPeopleLogic)
    const { toggleSection, setSearchQuery } = useActions(todayPeopleLogic)

    // The unread ticket count comes from the logic behind the classic nav's Support badge, so it is fetched once.
    // No unread tickets shows no number, like that badge.
    const rowCounts = { ...counts, support: customNavCountRegistry.conversations() || undefined }

    const renderRow = (row: TodayPeopleRow): JSX.Element => (
        <TodayPeopleNavRow key={row.key} row={row} meta={rowMeta(row.key, rowCounts)} active={activeRow === row.key} />
    )
    const noMatches =
        isSearching &&
        topRows.length === 0 &&
        rowSections.length === 0 &&
        matchingPinnedRows.length === 0 &&
        matchingRecentRows.length === 0

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={searchQuery}
                onQueryChange={setSearchQuery}
                searchLabel="Search people"
                dataAttr="people-sidebar-search"
            >
                {topRows.length > 0 && <div className="flex flex-col gap-px pb-2">{topRows.map(renderRow)}</div>}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">
                        Nothing in People matches your search.
                    </div>
                )}
                {matchingPinnedRows.length > 0 && (
                    <SidebarSection
                        label="Pinned"
                        open={isSectionOpen('pinned')}
                        count={matchingPinnedRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('pinned')}
                        divider
                        dataAttr="people-section-pinned"
                    >
                        {matchingPinnedRows.map((pin) => (
                            <SidebarRowEnter key={pin.key} pinKey={pin.key}>
                                <TodayPeopleRecentRow
                                    recent={pin}
                                    active={activeRow === peopleRecentRowKey(pin.href)}
                                    dataAttr="people-sidebar-pinned"
                                />
                            </SidebarRowEnter>
                        ))}
                    </SidebarSection>
                )}
                {matchingRecentRows.length > 0 && (
                    <SidebarSection
                        label="Recents"
                        open={isSectionOpen('recents')}
                        count={matchingRecentRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('recents')}
                        divider
                        dataAttr="people-section-recents"
                    >
                        {matchingRecentRows.map((recent) => (
                            <TodayPeopleRecentRow
                                key={recent.href}
                                recent={recent}
                                active={activeRow === peopleRecentRowKey(recent.href)}
                            />
                        ))}
                    </SidebarSection>
                )}
                {rowSections.map((section) => (
                    <SidebarSection
                        key={section.key}
                        label={section.label}
                        open={isSectionOpen(section.key)}
                        count={section.rows.length}
                        showCount={false}
                        onToggle={() => toggleSection(section.key)}
                        divider
                        dataAttr={`people-section-${section.key}`}
                    >
                        {section.rows.map(renderRow)}
                    </SidebarSection>
                ))}
            </SidebarSearchList>
        </div>
    )
}
