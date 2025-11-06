import './Cohorts.scss'

import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonDialog, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ListHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { cohortsSceneLogic } from 'scenes/cohorts/cohortsSceneLogic'
import { PersonsManagementSceneTabs } from 'scenes/persons-management/PersonsManagementSceneTabs'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { CohortType, ProductKey } from '~/types'

export const scene: SceneExport = {
    component: Cohorts,
    logic: cohortsSceneLogic,
}

export function Cohorts(): JSX.Element {
    const { cohorts, cohortsLoading, pagination, cohortFilters, shouldShowEmptyState, cohortSorting } =
        useValues(cohortsSceneLogic)
    const { deleteCohort, exportCohortPersons, setCohortFilters, setCohortSorting } = useActions(cohortsSceneLogic)
    const { searchParams } = useValues(router)

    const columns: LemonTableColumns<CohortType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            width: '30%',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            render: function Render(name, { id, description }) {
                return (
                    <>
                        <LemonTableLink
                            to={combineUrl(urls.cohort(id), searchParams).url}
                            title={name ? <>{name}</> : 'Untitled'}
                            description={description}
                        />
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
                'PostHog calculates what users belong to each cohort. This is then used when filtering on cohorts in the Trends page etc. Calculating happens every 24 hours, or whenever a cohort is updated',
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
                                <LemonButton to={urls.cohort(cohort.id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    to={
                                        combineUrl(urls.replay(), {
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
                                    targetBlank
                                >
                                    View session recordings
                                </LemonButton>
                                <LemonButton
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
                                    onClick={() => exportCohortPersons(cohort.id)}
                                    tooltip="Export all users belonging to this cohort in CSV format."
                                    fullWidth
                                >
                                    Export all columns for users
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete cohort?',
                                            description: `Are you sure you want to delete "${cohort.name}"?`,
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () =>
                                                    deleteCohort({ id: cohort.id, name: cohort.name, deleted: true }),
                                                size: 'small',
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'tertiary',
                                                size: 'small',
                                            },
                                        })
                                    }}
                                    fullWidth
                                >
                                    Delete cohort
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    const filtersSection = (
        <div className="flex justify-between gap-2 flex-wrap">
            <LemonInput
                className="w-60"
                type="search"
                placeholder="Search for cohorts"
                onChange={(search) => {
                    setCohortFilters({ search: search || undefined, page: 1 })
                }}
                value={cohortFilters.search}
            />
            <div className="flex items-center gap-2">
                <span>
                    <b>Type</b>
                </span>
                <LemonSelect
                    dropdownMatchSelectWidth={false}
                    size="small"
                    onChange={(type) => {
                        if (type) {
                            if (type === 'all') {
                                setCohortFilters({ type: undefined, page: 1 })
                            } else {
                                setCohortFilters({ type, page: 1 })
                            }
                        }
                    }}
                    options={[
                        { label: 'All', value: 'all' },
                        { label: 'Static', value: 'static' },
                        { label: 'Dynamic', value: 'dynamic' },
                    ]}
                    value={cohortFilters.type ?? 'all'}
                    data-attr="cohorts-filter-select-type"
                />
                <span className="ml-1">
                    <b>Created by</b>
                </span>
                <MemberSelect
                    defaultLabel="Any user"
                    value={cohortFilters.created_by_id ?? null}
                    onChange={(user) => {
                        if (!user) {
                            if (cohortFilters) {
                                const { created_by_id, ...restFilters } = cohortFilters
                                setCohortFilters({ ...restFilters, page: 1 }, true)
                            }
                        } else {
                            setCohortFilters({ created_by_id: user.id, page: 1 })
                        }
                    }}
                    data-attr="cohort-filters-select-created-by"
                />
            </div>
        </div>
    )

    return (
        <SceneContent>
            <PersonsManagementSceneTabs tabKey="cohorts" />

            <SceneTitleSection
                name={sceneConfigurations[Scene.Cohorts].name}
                description={sceneConfigurations[Scene.Cohorts].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Cohorts].iconType || 'default_icon_type',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        data-attr="new-cohort"
                        onClick={() => router.actions.push(urls.cohort('new'))}
                    >
                        New cohort
                    </LemonButton>
                }
            />

            <ProductIntroduction
                productName="Cohorts"
                productKey={ProductKey.COHORTS}
                thingName="cohort"
                description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn't convert."
                isEmpty={shouldShowEmptyState}
                docsURL="https://posthog.com/docs/data/cohorts"
                action={() => router.actions.push(urls.cohort('new'))}
                customHog={ListHog}
            />

            <div>{filtersSection}</div>
            <LemonTable
                columns={columns}
                loading={cohortsLoading}
                rowKey="id"
                pagination={pagination}
                dataSource={cohorts.results}
                nouns={['cohort', 'cohorts']}
                data-attr="cohorts-table"
                sorting={cohortSorting}
                onSort={(sorting) => {
                    setCohortSorting(sorting)
                }}
                useURLForSorting={false}
            />
        </SceneContent>
    )
}
