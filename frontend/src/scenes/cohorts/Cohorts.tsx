import React, { useState } from 'react'
import { deleteWithUndo } from 'lib/utils'
import { Button, Input } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { cohortsModel } from '../../models/cohortsModel'
import { useValues, useActions, kea } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'
import { Cohort, CohortFooter } from './Cohort'
import { Drawer } from 'lib/components/Drawer'
import { AvailableFeature, CohortType } from '~/types'
import api from 'lib/api'
import './Cohorts.scss'
import Fuse from 'fuse.js'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { Tooltip } from 'lib/components/Tooltip'
import { cohortsUrlLogicType } from './CohortsType'
import { Link } from 'lib/components/Link'
import { PROPERTY_MATCH_TYPE } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { urls } from 'scenes/urls'
import { LemonTable, LemonTableColumns, LemonTableColumn } from 'lib/components/LemonTable'
import { userLogic } from 'scenes/userLogic'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonSpacer } from 'lib/components/LemonRow'
import { combineUrl, router } from 'kea-router'

const NEW_COHORT: CohortType = {
    id: 'new',
    groups: [
        {
            id: Math.random().toString().substr(2, 5),
            matchType: PROPERTY_MATCH_TYPE,
            properties: [],
        },
    ],
}

const cohortsUrlLogic = kea<cohortsUrlLogicType>({
    path: ['scenes', 'cohorts', 'cohortsUrlLogic'],
    actions: {
        setOpenCohort: (cohort: CohortType | null) => ({ cohort }),
        exportCohortPersons: (id: CohortType['id']) => ({ id }),
    },
    reducers: {
        openCohort: [
            null as null | CohortType,
            {
                setOpenCohort: (_, { cohort }) => cohort,
            },
        ],
    },
    listeners: {
        exportCohortPersons: ({ id }) => {
            window.open(`/api/person.csv?cohort=${id}`, '_blank')
        },
    },
    actionToUrl: ({ values }) => ({
        setOpenCohort: () =>
            combineUrl(
                values.openCohort ? urls.cohort(values.openCohort.id || 'new') : urls.cohorts(),
                router.values.searchParams
            ).url,
    }),
    urlToAction: ({ actions, values }) => ({
        '/cohorts(/:cohortId)': async ({ cohortId }) => {
            if (
                cohortId &&
                cohortId !== 'new' &&
                cohortId !== 'personsModalNew' &&
                Number(cohortId) !== values.openCohort?.id
            ) {
                const cohort = await api.cohorts.get(parseInt(cohortId))
                actions.setOpenCohort(cohort)
            } else if (cohortId === 'new') {
                actions.setOpenCohort(NEW_COHORT)
            } else if (!cohortId) {
                actions.setOpenCohort(null)
            }
        },
    }),
})

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
    const { loadCohorts } = useActions(cohortsModel)
    const { openCohort } = useValues(cohortsUrlLogic)
    const { setOpenCohort, exportCohortPersons } = useActions(cohortsUrlLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { searchParams } = useValues(router)
    const [searchTerm, setSearchTerm] = useState(false as string | false)

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
                        <Link to={combineUrl(urls.cohort(id), searchParams).url}>
                            <h4 className="row-name">{name || 'Untitled'}</h4>
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
            render: function RenderCount(_: any, cohort: CohortType) {
                return cohort.count?.toLocaleString()
            },
            dataIndex: 'count',
            sorter: (a, b) => (a.count || 0) - (b.count || 0),
        },
        createdByColumn<CohortType>() as LemonTableColumn<CohortType, keyof CohortType | undefined>,
        createdAtColumn<CohortType>() as LemonTableColumn<CohortType, keyof CohortType | undefined>,
        {
            title: (
                <span>
                    <Tooltip title="PostHog calculates what users belong to each cohort. This is then used when filtering on cohorts in the Trends page etc. Calculating happens every 15 minutes, or whenever a cohort is updated.">
                        Last calculated
                        <InfoCircleOutlined style={{ marginLeft: 6 }} />
                    </Tooltip>
                </span>
            ),
            render: function RenderCalculation(_: any, cohort: CohortType) {
                if (cohort.is_static) {
                    return <>N/A</>
                }
                return cohort.is_calculating ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center' }}>
                        in progress <Spinner size="sm" style={{ marginLeft: 6 }} />
                    </span>
                ) : (
                    dayjs(cohort.last_calculation).fromNow()
                )
            },
        },
        {
            width: 0,
            render: function RenderActions(_, { id, name }) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton type="stealth" to={urls.cohort(id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    type="stealth"
                                    to={
                                        combineUrl(urls.sessionRecordings(), {
                                            filters: {
                                                properties: [
                                                    {
                                                        key: 'id',
                                                        label: name,
                                                        type: 'cohort',
                                                        value: id,
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
                                    type="stealth"
                                    onClick={() => exportCohortPersons(id)}
                                    tooltip="Export all users belonging to this cohort in CSV format."
                                    fullWidth
                                >
                                    Export users
                                </LemonButton>
                                <LemonSpacer />
                                <LemonButton
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() =>
                                        deleteWithUndo({
                                            endpoint: api.cohorts.determineDeleteEndpoint(),
                                            object: { name, id },
                                            callback: loadCohorts,
                                        })
                                    }
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
        <div>
            <PageHeader
                title="Cohorts"
                caption="Create lists of users who have something in common to use in analytics or feature flags."
            />
            <div>
                <Input.Search
                    allowClear
                    enterButton
                    placeholder="Search for cohorts"
                    style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                />
                <div className="mb float-right">
                    <Button
                        type="primary"
                        data-attr="create-cohort"
                        onClick={() => setOpenCohort(NEW_COHORT)}
                        icon={<PlusOutlined />}
                    >
                        New Cohort
                    </Button>
                </div>

                <LemonTable
                    columns={columns}
                    loading={cohortsLoading}
                    rowKey="id"
                    pagination={{ pageSize: 30 }}
                    dataSource={searchTerm ? searchCohorts(cohorts, searchTerm) : cohorts}
                    nouns={['cohort', 'cohorts']}
                />
                <Drawer
                    title={openCohort?.id === 'new' ? 'New cohort' : openCohort?.name}
                    className="cohorts-drawer"
                    onClose={() => setOpenCohort(null)}
                    destroyOnClose={true}
                    visible={!!openCohort}
                    footer={openCohort && <CohortFooter cohort={openCohort} />}
                >
                    {openCohort && <Cohort cohort={openCohort} />}
                </Drawer>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: Cohorts,
    logic: cohortsUrlLogic,
}
