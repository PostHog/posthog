import './Cohorts.scss'

import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { ListHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, CohortType, ProductKey } from '~/types'

import { cohortsModel } from '../../models/cohortsModel'

export function Cohorts(): JSX.Element {
    const { cohorts, cohortsSearch, cohortsLoading } = useValues(cohortsModel)
    const { deleteCohort, exportCohortPersons } = useActions(cohortsModel)
    const { hasAvailableFeature } = useValues(userLogic)
    const { searchParams } = useValues(router)
    const [searchTerm, setSearchTerm] = useState<string>('')
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const shouldShowEmptyState = cohorts?.length == 0 && !cohortsLoading
    const shouldShowProductIntroduction =
        !user?.has_seen_product_intro_for?.[ProductKey.COHORTS] &&
        !!featureFlags[FEATURE_FLAGS.SHOW_PRODUCT_INTRO_EXISTING_PRODUCTS]

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
                        {hasAvailableFeature(AvailableFeature.TEAM_COLLABORATION) && description && (
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
            {(shouldShowProductIntroduction || shouldShowEmptyState) && (
                <ProductIntroduction
                    productName="Cohorts"
                    productKey={ProductKey.COHORTS}
                    thingName="cohort"
                    description="Use cohorts to group people together, such as users who used your app in the last week, or people who viewed the signup page but didn’t convert."
                    isEmpty={cohorts?.length == 0}
                    docsURL="https://posthog.com/docs/data/cohorts"
                    action={() => router.actions.push(urls.cohort('new'))}
                    customHog={ListHog}
                />
            )}
            {!shouldShowEmptyState && (
                <>
                    <div className="flex justify-between items-center mb-4 gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search for cohorts"
                            onChange={setSearchTerm}
                            value={searchTerm}
                        />
                    </div>
                    <LemonTable
                        columns={columns}
                        loading={cohortsLoading}
                        rowKey="id"
                        pagination={{ pageSize: 100 }}
                        dataSource={searchTerm ? cohortsSearch(searchTerm) : cohorts ?? []}
                        nouns={['cohort', 'cohorts']}
                        data-attr="cohorts-table"
                    />
                </>
            )}
        </div>
    )
}
