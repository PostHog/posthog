import './TodayShell.scss'

import { useActions, useValues } from 'kea'

import {
    IconApps,
    IconBuilding,
    IconCheckbox,
    IconChevronDown,
    IconFeatures,
    IconFilter,
    IconMegaphone,
    IconNotebook,
    IconPeople,
    IconPerson,
    IconPulse,
    IconSupport,
} from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { ProductIconWrapper } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconColor } from '~/types'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'
import { TodayPeopleRow, TodayPeopleRowCounts, TodayPeopleRowKey, todayPeopleLogic } from './todayPeopleLogic'
import { TodayPeopleRecentType } from './todayPeopleRecentsLogic'

function colored(icon: JSX.Element, product: string): JSX.Element {
    const color: FileSystemIconColor = [`var(--color-product-${product}-light)`, `var(--color-product-${product}-dark)`]
    return (
        <ProductIconWrapper type="default_icon_type" colorOverride={color}>
            {icon}
        </ProductIconWrapper>
    )
}

const ROW_ICONS: Record<Exclude<TodayPeopleRowKey, `groups-${number}`>, JSX.Element> = {
    overview: <IconApps />,
    feed: <IconPulse />,
    tasks: <IconCheckbox />,
    persons: colored(<IconPerson />, 'product-analytics'),
    accounts: colored(<IconBuilding />, 'sources'),
    cohorts: colored(<IconPeople />, 'data-warehouse'),
    journeys: colored(<IconFilter />, 'customer-analytics'),
    notes: <IconNotebook />,
    announcements: <IconMegaphone />,
    feature_requests: <IconFeatures />,
    support: <IconSupport />,
}

const RECENT_ICONS: Record<TodayPeopleRecentType, JSX.Element> = {
    person: <IconPerson />,
    group: <IconBuilding />,
    cohort: <IconPeople />,
    account: <IconBuilding />,
    ticket: <IconSupport />,
}

function rowMeta(key: TodayPeopleRowKey, counts: TodayPeopleRowCounts): string | undefined {
    const count = counts[key as keyof TodayPeopleRowCounts]
    return count === undefined ? undefined : humanFriendlyLargeNumber(count)
}

export function TodayPeopleSidebar(): JSX.Element {
    const { primaryRows, moreRows, hasMoreRows, moreOpen, counts, recents, activeRow, collapsedSections } =
        useValues(todayPeopleLogic)
    const { toggleSection, toggleMore } = useActions(todayPeopleLogic)

    const renderRow = (row: TodayPeopleRow): JSX.Element => (
        <TodayPaneRow
            key={row.key}
            value={`browse:${row.key}`}
            label={row.label}
            meta={rowMeta(row.key, counts)}
            icon={row.key.startsWith('groups-') ? <IconBuilding /> : ROW_ICONS[row.key as keyof typeof ROW_ICONS]}
            to={row.href}
            active={activeRow === row.key}
            dataAttr={`people-sidebar-${row.key}`}
        />
    )

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
                {recents.length > 0 && (
                    <TodayPaneSection
                        label="Recents"
                        open={!collapsedSections.includes('recents')}
                        count={recents.length}
                        showCount={false}
                        onToggle={() => toggleSection('recents')}
                        divider
                        dataAttr="people-section-recents"
                    >
                        {recents.map((recent) => (
                            <TodayPaneRow
                                key={recent.href}
                                value={`recent:${recent.href}`}
                                label={recent.name}
                                icon={RECENT_ICONS[recent.type]}
                                to={recent.href}
                                active={activeRow === `recent:${recent.href}`}
                                dataAttr="people-sidebar-recent"
                            />
                        ))}
                    </TodayPaneSection>
                )}
            </TodayPaneSearchList>
        </div>
    )
}
