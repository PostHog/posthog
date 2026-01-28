import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CSSProperties, useEffect } from 'react'
import { List, useListRef } from 'react-window'

import { IconHome } from '@posthog/icons'

import { addToDashboardModalLogic } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { AutoSizer } from 'lib/components/AutoSizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardBasicType, InsightLogicProps } from '~/types'

interface DashboardRelationRowProps {
    dashboard: DashboardBasicType
    insightProps: InsightLogicProps
    canEditInsight: boolean
    isHighlighted: boolean
    isAlreadyOnDashboard: boolean
    style: CSSProperties
}

const DashboardRelationRow = ({
    style,
    isHighlighted,
    isAlreadyOnDashboard,
    dashboard,
    insightProps,
    canEditInsight,
}: DashboardRelationRowProps): JSX.Element => {
    const { addToDashboard, removeFromDashboard } = useActions(addToDashboardModalLogic(insightProps))
    const { dashboardWithActiveAPICall } = useValues(addToDashboardModalLogic(insightProps))

    const { currentTeam } = useValues(teamLogic)
    const isPrimary = dashboard.id === currentTeam?.primary_dashboard
    return (
        <div
            data-attr="dashboard-list-item"
            /* eslint-disable-next-line react/forbid-dom-props */
            style={style}
            className={clsx('flex items-center deprecated-space-x-2', isHighlighted && 'highlighted')}
        >
            <Link
                to={urls.dashboard(dashboard.id)}
                className="overflow-hidden text-ellipsis whitespace-nowrap"
                title={dashboard.name}
            >
                {dashboard.name || 'Untitled'}
            </Link>
            {isPrimary && (
                <Tooltip title="Primary dashboards are shown on the project home page">
                    <span className="flex items-center">
                        <IconHome className="text-warning text-base" />
                    </span>
                </Tooltip>
            )}
            <span className="grow" />
            <LemonButton
                type="secondary"
                status={isAlreadyOnDashboard ? 'danger' : 'default'}
                loading={dashboardWithActiveAPICall === dashboard.id}
                disabledReason={
                    !canEditInsight
                        ? "You don't have permission to edit this dashboard"
                        : dashboardWithActiveAPICall
                          ? 'Loading...'
                          : ''
                }
                size="small"
                onClick={(e) => {
                    e.preventDefault()
                    isAlreadyOnDashboard ? removeFromDashboard(dashboard.id) : addToDashboard(dashboard.id)
                }}
            >
                {isAlreadyOnDashboard ? 'Remove from dashboard' : 'Add to dashboard'}
            </LemonButton>
        </div>
    )
}

interface DashboardRowProps {
    orderedDashboards: DashboardBasicType[]
    currentDashboards: DashboardBasicType[]
    insightProps: InsightLogicProps
    canEditInsight: boolean
    scrollIndex: number
}

const DashboardRow = ({
    index,
    style,
    orderedDashboards,
    currentDashboards,
    insightProps,
    canEditInsight,
    scrollIndex,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & DashboardRowProps): JSX.Element => {
    return (
        <DashboardRelationRow
            dashboard={orderedDashboards[index]}
            insightProps={insightProps}
            canEditInsight={canEditInsight}
            isHighlighted={index === scrollIndex}
            isAlreadyOnDashboard={currentDashboards.some(
                (currentDashboard) => currentDashboard.id === orderedDashboards[index].id
            )}
            style={style}
        />
    )
}

interface SaveToDashboardModalProps {
    isOpen: boolean
    closeModal: () => void
    insightProps: InsightLogicProps
    canEditInsight: boolean
}

export function AddToDashboardModal({
    isOpen,
    closeModal,
    insightProps,
    canEditInsight,
}: SaveToDashboardModalProps): JSX.Element {
    const logic = addToDashboardModalLogic(insightProps)

    const { searchQuery, currentDashboards, orderedDashboards, scrollIndex } = useValues(logic)
    const { setSearchQuery, addNewDashboard } = useActions(logic)
    const listRef = useListRef(null)

    useEffect(() => {
        if (scrollIndex >= 0 && listRef.current) {
            listRef.current.scrollToRow({ index: scrollIndex, align: 'smart' })
        }
    }, [scrollIndex])

    const rowProps: DashboardRowProps = {
        orderedDashboards,
        currentDashboards,
        insightProps,
        canEditInsight,
        scrollIndex,
    }

    return (
        <LemonModal
            onClose={() => {
                closeModal()
                setSearchQuery('')
            }}
            isOpen={isOpen}
            title="Add to dashboard"
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton
                            type="secondary"
                            onClick={addNewDashboard}
                            disabledReason={
                                !canEditInsight
                                    ? 'You do not have permission to add this insight to dashboards'
                                    : undefined
                            }
                        >
                            Add to a new dashboard
                        </LemonButton>
                    </div>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                </>
            }
        >
            <div className="deprecated-space-y-2 w-192 max-w-full">
                <LemonInput
                    data-attr="dashboard-searchfield"
                    type="search"
                    fullWidth
                    placeholder="Search for dashboards..."
                    value={searchQuery}
                    onChange={(newValue) => setSearchQuery(newValue)}
                    autoFocus
                />
                <div className="text-secondary">
                    This insight is referenced on <strong className="text-text-3000">{currentDashboards.length}</strong>{' '}
                    {pluralize(currentDashboards.length, 'dashboard', 'dashboards', false)}
                </div>
                <div className="min-h-[420px]">
                    <AutoSizer
                        renderProp={({ height, width }) =>
                            height && width ? (
                                <List<DashboardRowProps>
                                    listRef={listRef}
                                    style={{ width, height }}
                                    rowCount={orderedDashboards.length}
                                    overscanCount={100}
                                    rowHeight={40}
                                    rowComponent={DashboardRow}
                                    rowProps={rowProps}
                                />
                            ) : null
                        }
                    />
                </div>
            </div>
        </LemonModal>
    )
}
