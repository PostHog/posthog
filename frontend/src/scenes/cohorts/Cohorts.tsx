import { useState } from 'react'
import { cohortsModel } from '../../models/cohortsModel'
import { useValues, useActions } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { AvailableFeature, CohortType } from '~/types'
import './Cohorts.scss'
import Fuse from 'fuse.js'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { Link } from 'lib/components/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { urls } from 'scenes/urls'
import { LemonTable, LemonTableColumns, LemonTableColumn } from 'lib/components/LemonTable'
import { userLogic } from 'scenes/userLogic'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { combineUrl, router } from 'kea-router'
import { LemonInput } from '@posthog/lemon-ui'

const searchCohorts = (sources: CohortType[], search: string): CohortType[] => {
    return new Fuse(sources, {
        keys: ['name'],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export function Cohorts(): JSX.Element {
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    const { deleteCohort, exportCohortPersons } = useActions(cohortsModel)
    const { hasAvailableFeature } = useValues(userLogic)
    const { searchParams } = useValues(router)
    const [searchTerm, setSearchTerm] = useState<string>('')

    const columns: LemonTableColumns<CohortType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            className: 'ph-no-capture',
            width: '30%',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            render: function Render(name, { id, description }) {
                return (
                    <>
                        <Link to={combineUrl(urls.cohort(id), searchParams).url} className="row-name">
                            {name || 'Untitled'}
                        </Link>
                        {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && description && (
                            <span className="row-description">{description}</span>
                        )}
                    </>
                )
            },
        },
        {
            title: 'Users in cohort',
            align: 'right',
            render: function RenderCount(_: any, cohort: CohortType) {
                return cohort.count?.toLocaleString()
            },
            dataIndex: 'count',
            sorter: (a, b) => (a.count || 0) - (b.count || 0),
        },
        createdByColumn<CohortType>() as LemonTableColumn<CohortType, keyof CohortType | undefined>,
        createdAtColumn<CohortType>() as LemonTableColumn<CohortType, keyof CohortType | undefined>,
        {
            title: 'Last calculated',
            tooltip:
                'PostHog calculates what users belong to each cohort. This is then used when filtering on cohorts in the Trends page etc. Calculating happens every 15 minutes, or whenever a cohort is updated',
            render: function RenderCalculation(_: any, cohort: CohortType) {
                if (cohort.is_static) {
                    return <>N/A</>
                }
                return cohort.is_calculating ? (
                    <span className="flex items-center">
                        in progress <Spinner className="ml-2" />
                    </span>
                ) : (
                    dayjs(cohort.last_calculation).fromNow()
                )
            },
        },
        {
            width: 0,
            render: function RenderActions(_, cohort) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton status="stealth" to={urls.cohort(cohort.id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    to={
                                        combineUrl(urls.sessionRecordings(), {
                                            filters: {
                                                properties: [
                                                    {
                                                        key: 'id',
                                                        label: cohort.name,
                                                        type: 'cohort',
                                                        value: cohort.id,
                                                    },
                                                ],
                                            },
                                        }).url
                                    }
                                    fullWidth
                                >
                                    View session recordings
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    onClick={() =>
                                        exportCohortPersons(cohort.id, [
                                            'distinct_ids.0',
                                            'id',
                                            'name',
                                            'properties.email',
                                        ])
                                    }
                                    tooltip="Export specific columns for users belonging to this cohort in CSV format. Includes distinct id, internal id, email, and name"
                                    fullWidth
                                >
                                    Export important columns for users
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => exportCohortPersons(cohort.id)}
                                    tooltip="Export all users belonging to this cohort in CSV format."
                                    fullWidth
                                >
                                    Export all columns for users
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton status="danger" onClick={() => deleteCohort(cohort)} fullWidth>
                                    Delete cohort
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader
                title="Cohorts"
                caption="Create lists of users who have something in common to use in analytics or feature flags."
            />
            <div className="flex justify-between items-center mb-4 gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search for cohorts"
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
                <LemonButton
                    type="primary"
                    data-attr="create-cohort"
                    onClick={() => router.actions.push(urls.cohort('new'))}
                >
                    New Cohort
                </LemonButton>
            </div>
            <LemonTable
                columns={columns}
                loading={cohortsLoading}
                rowKey="id"
                pagination={{ pageSize: 100 }}
                dataSource={searchTerm ? searchCohorts(cohorts, searchTerm) : cohorts}
                nouns={['cohort', 'cohorts']}
                data-attr="cohorts-table"
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Cohorts,
    logic: cohortsModel,
}
