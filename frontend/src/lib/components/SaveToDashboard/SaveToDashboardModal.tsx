import React, { FormEvent } from 'react'
import { useActions, useValues } from 'kea'
import { Select, Modal } from 'antd'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { saveToDashboardModalLogic } from 'lib/components/SaveToDashboard/saveToDashboardModalLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { lemonToast } from '../lemonToast'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import './AddToDashboard.scss'
import { IconMagnifier } from 'lib/components/icons'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { LemonButton } from 'lib/components/LemonButton'
import { Link } from 'lib/components/Link'
import { DashboardType, InsightModel } from '~/types'

interface SaveToDashboardModalProps {
    visible: boolean
    closeModal: () => void
    insight: Partial<InsightModel>
}

export function AddToDashboardModal({ visible, closeModal, insight }: SaveToDashboardModalProps): JSX.Element {
    const logic = saveToDashboardModalLogic({
        id: insight.short_id,
        insight: insight,
        fromDashboard: insight.dashboards?.[0] || undefined,
    })

    const { dashboardId, searchQuery, currentDashboards, orderedDashboards } = useValues(logic)
    const { setSearchQuery } = useActions(logic)
    // const { addNewDashboard, setDashboardId } = useActions(logic)
    const { reportSavedInsightToDashboard } = useActions(eventUsageLogic)
    const { insightLoading } = useValues(insightLogic)
    const { updateInsight } = useActions(insightLogic)

    async function save(event: MouseEvent | FormEvent): Promise<void> {
        event.preventDefault()
        updateInsight({ ...insight, dashboards: [dashboardId] }, () => {
            reportSavedInsightToDashboard()
            lemonToast.success('Insight added to dashboard', {
                button: {
                    label: 'View dashboard',
                    action: () => router.actions.push(urls.dashboard(dashboardId)),
                },
            })
            closeModal()
        })
    }

    async function addToDashboard(dashboardToAdd: number): Promise<void> {
        updateInsight({ ...insight, dashboards: [...(insight.dashboards || []), dashboardToAdd] }, () => {
            reportSavedInsightToDashboard()
            lemonToast.success('Insight added to dashboard', {
                button: {
                    label: 'View dashboard',
                    action: () => router.actions.push(urls.dashboard(dashboardId)),
                },
            })
        })
    }

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        const dashboard = orderedDashboards[rowIndex]
        const isAlreadyOnDashboard = currentDashboards.some(
            (currentDashboard: DashboardType) => currentDashboard.id === dashboard.id
        )
        return (
            <div style={style} className="modal-row">
                <Link to={urls.dashboard(dashboard.id)}>{dashboard.name || 'Untitled'}</Link>
                <LemonButton
                    type={isAlreadyOnDashboard ? 'primary' : 'secondary'}
                    compact={true}
                    onClick={(e) => {
                        e.preventDefault()
                        isAlreadyOnDashboard ? () => {} : addToDashboard(dashboard.id)
                    }}
                >
                    {isAlreadyOnDashboard ? 'Added' : 'Add to dashboard'}
                </LemonButton>
            </div>
        )
    }

    return (
        <Modal
            onOk={(e) => void save(e)}
            onCancel={closeModal}
            afterClose={closeModal}
            confirmLoading={insightLoading}
            visible={visible}
            title="add to dashboard"
            wrapClassName="add-to-dashboard-modal"
            footer={
                <div className="modal-row">
                    <LemonButton type="secondary" compact={true}>
                        Add to a new dashboard
                    </LemonButton>
                    <LemonButton type="secondary" compact={true} onClick={() => closeModal()}>
                        Close
                    </LemonButton>
                </div>
            }
        >
            <LemonInput
                data-attr="dashboard-searchfield"
                placeholder={`Search for dashboards...`}
                value={searchQuery}
                className={searchQuery && 'LemonInput--with-input'}
                icon={<IconMagnifier />}
                onChange={(newValue) => setSearchQuery(newValue)}
            />
            <div className={'existing-links-info'}>
                This insight is referenced on <strong>{insight.dashboards?.length}</strong> dashboards (remove all)
            </div>
            <div className="list-wrapper">
                <AutoSizer>
                    {({ height, width }) => (
                        <List
                            width={width}
                            height={height}
                            rowCount={orderedDashboards.length}
                            overscanRowCount={100}
                            rowHeight={40}
                            rowRenderer={renderItem}
                            onRowsRendered={(args) => {
                                console.log({ ...args }, 'on rows rendered')
                            }}
                            scrollToIndex={-1}
                        />
                    )}
                </AutoSizer>
            </div>
            <hr className="separator" />
        </Modal>
    )
}

export function SaveToDashboardModal({ visible, closeModal, insight }: SaveToDashboardModalProps): JSX.Element {
    const logic = saveToDashboardModalLogic({
        id: insight.short_id,
        insight: insight,
        fromDashboard: insight.dashboards?.[0] || undefined,
    })
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { dashboardId } = useValues(logic)
    const { addNewDashboard, setDashboardId } = useActions(logic)
    const { reportSavedInsightToDashboard } = useActions(eventUsageLogic)
    const { insightLoading } = useValues(insightLogic)
    const { updateInsight } = useActions(insightLogic)

    async function save(event: MouseEvent | FormEvent): Promise<void> {
        event.preventDefault()
        updateInsight({ ...insight, dashboards: [dashboardId] }, () => {
            reportSavedInsightToDashboard()
            lemonToast.success('Insight added to dashboard', {
                button: {
                    label: 'View dashboard',
                    action: () => router.actions.push(urls.dashboard(dashboardId)),
                },
            })
            closeModal()
        })
    }

    return (
        <Modal
            onOk={(e) => void save(e)}
            onCancel={closeModal}
            afterClose={closeModal}
            confirmLoading={insightLoading}
            visible={visible}
            title="Add to dashboard"
            okText="Add insight to dashboard"
        >
            <form onSubmit={(e) => void save(e)}>
                <label>Dashboard</label>
                <Select
                    data-attr="add-to-dashboard-select"
                    value={dashboardId}
                    onChange={(id) => (id === 'new' ? addNewDashboard() : setDashboardId(id))}
                    style={{ width: '100%' }}
                >
                    {nameSortedDashboards.map((dashboard, idx) => (
                        <Select.Option
                            data-attr={`add-to-dashboard-option-${idx}`}
                            key={dashboard.id}
                            value={dashboard.id}
                        >
                            {dashboard.name}
                        </Select.Option>
                    ))}
                    <Select.Option value="new">+ New Dashboard</Select.Option>
                </Select>
            </form>
        </Modal>
    )
}
