import { useActions, useValues } from 'kea'

import { IconBuilding, IconDashboard, IconMap, IconPeople, IconPerson } from '@posthog/icons'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'
import { TodayPeopleRowKey, todayPeopleLogic } from './todayPeopleLogic'

const ROW_ICONS: Record<TodayPeopleRowKey, JSX.Element> = {
    overview: <IconDashboard />,
    persons: <IconPerson />,
    accounts: <IconBuilding />,
    cohorts: <IconPeople />,
    journeys: <IconMap />,
}

export function TodayPeopleSidebar(): JSX.Element {
    const { rows, recentCohorts, activeRow, collapsedSections } = useValues(todayPeopleLogic)
    const { toggleSection } = useActions(todayPeopleLogic)

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            {/* The rows are list options that need the pane list around them; this pane has no search, so the field stays hidden. */}
            <TodayPaneSearchList
                query=""
                onQueryChange={() => {}}
                searchLabel="Search people"
                dataAttr="people-sidebar-search"
                className="[&>div:first-child]:hidden"
            >
                <div className="flex flex-col gap-px pb-2">
                    {rows.map((row) => (
                        <TodayPaneRow
                            key={row.key}
                            value={`browse:${row.key}`}
                            label={row.label}
                            icon={ROW_ICONS[row.key]}
                            to={row.href}
                            active={activeRow === row.key}
                            dataAttr={`people-sidebar-${row.key}`}
                        />
                    ))}
                </div>
                {recentCohorts.length > 0 && (
                    <TodayPaneSection
                        label="Recents"
                        open={!collapsedSections.includes('recents')}
                        count={recentCohorts.length}
                        showCount={false}
                        onToggle={() => toggleSection('recents')}
                        divider
                        dataAttr="people-section-recents"
                    >
                        {recentCohorts.map((cohort) => (
                            <TodayPaneRow
                                key={cohort.id}
                                value={`recent:${cohort.id}`}
                                label={cohort.name}
                                icon={iconForType('cohort')}
                                to={cohort.href}
                                active={activeRow === `recent:${cohort.id}`}
                                dataAttr="people-sidebar-recent"
                            />
                        ))}
                    </TodayPaneSection>
                )}
            </TodayPaneSearchList>
        </div>
    )
}
