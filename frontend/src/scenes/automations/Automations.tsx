import { useActions, useValues } from 'kea'

import { PageHeader } from 'lib/components/PageHeader'
import { urls } from 'scenes/urls'
import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { automationsLogic } from './automationsLogic'
import { Automation } from './schema'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { AutomationsTabs } from '~/types'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
// import { AppMetricsGraph } from 'scenes/apps/AppMetricsGraph'
import { More } from 'lib/lemon-ui/LemonButton/More'

export function Automations(): JSX.Element {
    const { filteredAutomations, automationsLoading, tab, searchTerm } = useValues(automationsLogic)
    const { setAutomationsTab, setSearchTerm, deleteAutomation } = useActions(automationsLogic)

    const columns: LemonTableColumns<Automation> = [
        {
            title: normalizeColumnTitle('Name'),
            dataIndex: 'name',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            render: function Render(_, automation: Automation) {
                return (
                    <>
                        <Link to={automation.id ? urls.automation(automation.id) : undefined}>
                            <span className="row-name">{stringWithWBR(automation.name, 17)}</span>
                        </Link>
                        {automation.description && <span className="row-description">{automation.description}</span>}
                    </>
                )
            },
        },
        createdByColumn<Automation>() as LemonTableColumn<Automation, keyof Automation | undefined>,
        createdAtColumn<Automation>() as LemonTableColumn<Automation, keyof Automation | undefined>,
        // {
        //     title: 'Status',
        //     key: 'status',
        //     render: function Render(_, experiment: Experiment) {
        //         const statusColors = { running: 'green', draft: 'default', complete: 'purple' }
        //         const status = getExperimentStatus(experiment)
        //         return (
        //             <Tag color={statusColors[status]} style={{ fontWeight: 600 }}>
        //                 {status.toUpperCase()}
        //             </Tag>
        //         )
        //     },
        //     align: 'center',
        //     sorter: (a, b) => {
        //         const statusA = getExperimentStatus(a)
        //         const statusB = getExperimentStatus(b)

        //         const score = {
        //             draft: 1,
        //             running: 2,
        //             complete: 3,
        //         }
        //         return score[statusA] > score[statusB] ? 1 : -1
        //     },
        // },
        {
            width: 0,
            render: function Render(_, automation: Automation) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    to={urls.automation(`${automation.id}`)}
                                    size="small"
                                    fullWidth
                                >
                                    View
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() => deleteAutomation(automation.id as number)}
                                    data-attr={`automation-${automation.id}-dropdown-remove`}
                                    fullWidth
                                >
                                    Delete automation
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <PageHeader
                title={<div className="flex items-center">Automations</div>}
                caption={
                    <>
                        A nice text{' '}
                        <Link
                            data-attr="automation-info"
                            to="https://github.com/PostHog/posthog/pull/14914"
                            target="_blank"
                        >
                            More info
                        </Link>
                    </>
                }
                buttons={
                    <LemonButton type="primary" data-attr="create-experiment" to={urls.automation('new')}>
                        New automation
                    </LemonButton>
                }
                tabbedPage
            />
            <LemonTabs
                activeKey={tab}
                onChange={(newKey) => setAutomationsTab(newKey)}
                tabs={[
                    { key: AutomationsTabs.All, label: 'All automations' },
                    { key: AutomationsTabs.Yours, label: 'Your automations' },
                    { key: AutomationsTabs.Archived, label: 'Archived automations' },
                ]}
            />
            <div className="flex justify-between mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search for Automations"
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
                {/* <div className="flex items-center gap-2">
                    <span>
                        <b>Status</b>
                    </span>
                    <LemonSelect
                        onChange={(status) => {
                            if (status) {
                                setSearchStatus(status as ExperimentStatus | 'all')
                            }
                        }}
                        options={[
                            { label: 'All', value: 'all' },
                            { label: 'Draft', value: ExperimentStatus.Draft },
                            { label: 'Running', value: ExperimentStatus.Running },
                            { label: 'Complete', value: ExperimentStatus.Complete },
                        ]}
                        value="all"
                        dropdownMaxContentWidth
                    />
                </div> */}
            </div>
            {/* <div className="mb-4">
                <h2>Automation trends</h2>
                <AppMetricsGraph
                // tab={tab}
                // metrics={appMetricsResponse?.metrics}
                // metricsLoading={appMetricsResponseLoading}
                />
            </div> */}

            <LemonTable
                dataSource={filteredAutomations}
                columns={columns}
                rowKey="id"
                loading={automationsLoading}
                defaultSorting={{
                    columnKey: 'created_at',
                    order: -1,
                }}
                noSortingCancellation
                pagination={{ pageSize: 100 }}
                nouns={['automation', 'automations']}
                data-attr="automation-table"
            />
        </>
    )
}
