import './Cohorts.scss'

import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

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
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { CohortType, ProductKey } from '~/types'

const RESOURCE_TYPE = 'cohort'

export const scene: SceneExport = {
    component: Cohorts,
    logic: cohortsSceneLogic,
}

export function Cohorts(): JSX.Element {
    const { cohorts, cohortsLoading, pagination, cohortFilters } = useValues(cohortsSceneLogic)
    const { deleteCohort, exportCohortPersons, setCohortFilters } = useActions(cohortsSceneLogic)
    const { searchParams } = useValues(router)
    const [searchTerm, setSearchTerm] = useState(cohortFilters.search || '')

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
                                        deleteCohort({ id: cohort.id, name: cohort.name, deleted: true })
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

    return (
        <SceneContent forceNewSpacing>
            <PersonsManagementSceneTabs
                tabKey="cohorts"
                buttons={
                    <LemonButton
                        type="primary"
                        data-attr="new-cohort"
                        onClick={() => router.actions.push(urls.cohort('new'))}
                    >
                        New cohort
                    </LemonButton>
                }
            />

            <SceneTitleSection
                name="Cohorts"
                description="A catalog of identified persons and your created cohorts."
                resourceType={{
                    type: RESOURCE_TYPE,
                }}
                docsURL="https://posthog.com/docs/data/cohorts"
            />
            <SceneDivider />

            <ProductIntroduction
                productName="Cohorts"
                productKey={ProductKey.COHORTS}
                thingName="cohort"
                description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn't convert."
                isEmpty={cohorts.count == 0 && !cohortsLoading && !searchTerm}
                docsURL="https://posthog.com/docs/data/cohorts"
                action={() => router.actions.push(urls.cohort('new'))}
                customHog={ListHog}
            />

            <div className="flex justify-between items-center mb-0 gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search for cohorts"
                    onChange={(search) => {
                        setSearchTerm(search)
                        setCohortFilters({ search: search || undefined, page: 1 })
                    }}
                    value={searchTerm}
                />
            </div>
            <LemonTable
                columns={columns}
                loading={cohortsLoading}
                rowKey="id"
                pagination={pagination}
                dataSource={cohorts.results}
                nouns={['cohort', 'cohorts']}
                data-attr="cohorts-table"
            />
        </SceneContent>
    )
}
