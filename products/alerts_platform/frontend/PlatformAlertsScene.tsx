import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PlatformAlertDestinationIcons } from './PlatformAlertDestinationIcons'
import {
    PlatformAlertListRow,
    SOURCE_KINDS,
    canExpand,
    describeGroup,
    describeInterval,
    describeSchedule,
    listRowMute,
} from './platformAlertFormat'
import { PlatformAlertMuteMarker } from './PlatformAlertMuteMarker'
import { PLATFORM_ALERTS_PAGE_SIZE, PlatformAlertsTab, platformAlertsLogic } from './platformAlertsLogic'
import { PlatformAlertStateLabel } from './PlatformAlertStateLabel'
import { PlatformAlertStateSummary } from './PlatformAlertStateSummary'
import { PlatformAlertRouting } from './routing/PlatformAlertRouting'

const SCROLL_BREATHING_ROOM_PX = 320

export const scene: SceneExport = {
    component: PlatformAlertsScene,
    logic: platformAlertsLogic,
}

function listColumns(
    expandedIds: readonly string[],
    toggleExpanded: (id: string) => void
): LemonTableColumns<PlatformAlertListRow> {
    return [
        {
            title: 'Type',
            width: 0,
            render: (_, row) => {
                if (row.kind === 'group') {
                    return null
                }
                const { label, iconType } = SOURCE_KINDS[row.configuration.source_kind]
                return (
                    <Tooltip title={label} placement="top-start">
                        <span
                            className="group/colorful-product-icons colorful-product-icons-true flex text-xl"
                            role="img"
                            aria-label={label}
                            data-attr="platform-alerts-row-type"
                        >
                            {iconForType(iconType)}
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Name',
            render: (_, row) => {
                const { configuration } = row
                if (row.kind === 'group') {
                    return (
                        <span className="block w-0 min-w-full break-words pl-7 font-mono text-xs" translate="no">
                            {describeGroup(row.group, configuration.grouping.keys ?? [])}
                        </span>
                    )
                }
                const expanded = expandedIds.includes(configuration.id)
                return (
                    <div className="flex items-center gap-1">
                        {canExpand(configuration) ? (
                            <LemonButton
                                size="xsmall"
                                icon={<IconChevronRight className={expanded ? 'rotate-90' : undefined} />}
                                tooltip={expanded ? 'Hide groups' : 'Show groups'}
                                aria-expanded={expanded}
                                onClick={() => toggleExpanded(configuration.id)}
                                data-attr="platform-alerts-row-toggle-groups"
                            />
                        ) : (
                            <span className="w-6 shrink-0" />
                        )}
                        <Link to={urls.platformAlert(configuration.id)} data-attr="platform-alerts-row-link">
                            {configuration.name}
                        </Link>
                    </div>
                )
            },
        },
        {
            title: 'State',
            render: (_, row) =>
                row.kind === 'group' ? (
                    <div className="flex flex-wrap items-center gap-x-2">
                        <PlatformAlertStateLabel status={row.group.state} />
                        {row.group.state === 'firing' && row.group.firing_started_at && (
                            <span className="inline-flex items-center gap-1 whitespace-nowrap text-muted">
                                <span>since</span>
                                <TZLabel time={row.group.firing_started_at} />
                            </span>
                        )}
                    </div>
                ) : (
                    <PlatformAlertStateSummary configuration={row.configuration} />
                ),
        },
        {
            title: 'Destinations',
            render: (_, row) => {
                const mute = listRowMute(row, new Date())
                return (
                    <div className="flex flex-wrap items-center gap-1.5">
                        {row.kind !== 'group' && (
                            <PlatformAlertDestinationIcons
                                types={row.configuration.destination_types}
                                enabled={row.configuration.enabled}
                            />
                        )}
                        {mute && <PlatformAlertMuteMarker mute={mute} />}
                    </div>
                )
            },
        },
        {
            title: 'Interval',
            render: (_, row) =>
                row.kind === 'group' ? null : (
                    <Tooltip title={describeSchedule(row.configuration)}>
                        <span className="border-dotted border-b">{describeInterval(row.configuration)}</span>
                    </Tooltip>
                ),
        },
    ]
}

export function PlatformAlertsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        configurationsPage,
        configurationsPageLoading,
        configurationsError,
        page,
        activeTab,
        listRows,
        expandedIds,
    } = useValues(platformAlertsLogic)
    const { loadConfigurations, setPage, setActiveTab, toggleExpanded } = useActions(platformAlertsLogic)
    const columns = useMemo(() => listColumns(expandedIds, toggleExpanded), [expandedIds, toggleExpanded])
    // The table's own pagination counts its rows, and an open alert adds a row for each group.
    const alertPagination = usePagination(configurationsPage?.results ?? [], {
        controlled: true,
        pageSize: PLATFORM_ALERTS_PAGE_SIZE,
        currentPage: page,
        entryCount: configurationsPage?.count ?? 0,
        onForward: configurationsPage?.next ? () => setPage(page + 1) : undefined,
        onBackward: page > 1 ? () => setPage(page - 1) : undefined,
    })
    const listRef = useRef<HTMLDivElement>(null)
    const shownPageRef = useRef(page)
    useEffect(() => {
        if (shownPageRef.current === page) {
            return
        }
        shownPageRef.current = page
        if (!listRef.current) {
            return
        }
        const offsetTop = listRef.current.getBoundingClientRect().top - SCROLL_BREATHING_ROOM_PX
        if (offsetTop < 0) {
            const scrollContainer = document.querySelector('main') ?? window
            scrollContainer.scrollBy(0, offsetTop)
        }
    }, [page])

    if (!featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS]) {
        return <NotFound object="page" />
    }

    const configurations = configurationsError ? (
        <LemonBanner
            type="error"
            action={{
                children: 'Retry',
                onClick: () => loadConfigurations(),
                'data-attr': 'platform-alerts-retry',
            }}
        >
            Couldn't load alert configurations. Try again in a moment.
        </LemonBanner>
    ) : (
        <div ref={listRef}>
            <LemonTable
                dataSource={listRows}
                columns={columns}
                loading={configurationsPageLoading || configurationsPage === null}
                rowKey={(row) => (row.kind === 'group' ? row.group.id : row.configuration.id)}
                rowClassName={(row) => (row.kind === 'group' ? 'bg-surface-secondary' : null)}
                emptyState="No alert configurations on the platform for this project yet."
            />
            <PaginationControl {...alertPagination} nouns={['alert', 'alerts']} bordered />
        </div>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Platform alerts"
                description="Alert configurations evaluated by the shared alerts platform."
                resourceType={{ type: 'inbox' }}
            />
            {featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS_ROUTING] ? (
                <LemonTabs<PlatformAlertsTab>
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    sceneInset
                    tabs={[
                        { key: 'alerts', label: 'Alerts', content: configurations },
                        { key: 'routing', label: 'Routing', content: <PlatformAlertRouting /> },
                    ]}
                />
            ) : (
                configurations
            )}
        </SceneContent>
    )
}
