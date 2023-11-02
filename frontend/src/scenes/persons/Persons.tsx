import { useValues, useActions, BindLogic } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Col, Popconfirm } from 'antd'
import { personsLogic } from './personsLogic'
import { CohortType, PersonType, ProductKey } from '~/types'
import { PersonsSearch } from './PersonsSearch'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconExport } from 'lib/lemon-ui/icons'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Link } from '@posthog/lemon-ui'

interface PersonsProps {
    cohort?: CohortType['id']
}

export function Persons({ cohort }: PersonsProps = {}): JSX.Element {
    return (
        <BindLogic logic={personsLogic} props={{ cohort: cohort, syncWithUrl: !cohort, fixedProperties: undefined }}>
            <PersonsScene />
        </BindLogic>
    )
}

interface PersonsSceneProps {
    extraSceneActions?: JSX.Element[]
    compact?: boolean
    showFilters?: boolean
    showExportAction?: boolean
    extraColumns?: LemonTableColumn<PersonType, keyof PersonType | undefined>[]
    showSearch?: boolean
    emptyState?: JSX.Element
}

export function PersonsScene({
    extraSceneActions,
    compact,
    extraColumns,
    emptyState,
    showFilters = true,
    showExportAction = true,
    showSearch = true,
}: PersonsSceneProps): JSX.Element {
    const { loadPersons, setListFilters } = useActions(personsLogic)
    const { persons, listFilters, personsLoading, exporterProps, apiDocsURL } = useValues(personsLogic)
    const shouldShowEmptyState = !personsLoading && persons.results.length === 0 && !listFilters.search

    return (
        <>
            {shouldShowEmptyState ? (
                <ProductIntroduction
                    productName="Persons"
                    thingName="person"
                    productKey={ProductKey.PERSONS}
                    description="PostHog tracks user behaviour, whether or not the user is logged in or anonymous. Once you've sent some data, the associated persons will show up here."
                    docsURL="https://posthog.com/docs/getting-started/install"
                    actionElementOverride={
                        <LemonButton type="primary" onClick={() => router.actions.push(urls.ingestion() + '/platform')}>
                            Start sending data
                        </LemonButton>
                    }
                    isEmpty={true}
                />
            ) : (
                <div className="persons-list">
                    <div className="space-y-2">
                        <div className="flex justify-between items-center gap-2">
                            {showSearch && (
                                <Col>
                                    <PersonsSearch />
                                </Col>
                            )}
                            <Col className="flex flex-row gap-2">
                                {showExportAction && (
                                    <Popconfirm
                                        placement="topRight"
                                        title={
                                            <>
                                                Exporting by CSV is limited to 10,000 users.
                                                <br />
                                                To export more, please use <Link to={apiDocsURL}>the API</Link>. Do you
                                                want to export by CSV?
                                            </>
                                        }
                                        onConfirm={() => triggerExport(exporterProps[0])}
                                    >
                                        <LemonButton
                                            type="secondary"
                                            icon={<IconExport style={{ color: 'var(--primary)' }} />}
                                        >
                                            {listFilters.properties && listFilters.properties.length > 0 ? (
                                                <div style={{ display: 'block' }}>
                                                    Export (<strong>{listFilters.properties.length}</strong> filter)
                                                </div>
                                            ) : (
                                                'Export'
                                            )}
                                        </LemonButton>
                                    </Popconfirm>
                                )}
                                {extraSceneActions ? extraSceneActions : null}
                            </Col>
                        </div>
                        {showFilters && (
                            <PropertyFilters
                                pageKey="persons-list-page"
                                propertyFilters={listFilters.properties}
                                onChange={(properties) => {
                                    setListFilters({ properties })
                                    loadPersons()
                                }}
                                endpoint="person"
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                                showConditionBadge
                            />
                        )}
                        <PersonsTable
                            people={persons.results}
                            loading={personsLoading}
                            hasPrevious={!!persons.previous}
                            hasNext={!!persons.next}
                            loadPrevious={() => loadPersons(persons.previous)}
                            loadNext={() => loadPersons(persons.next)}
                            compact={compact}
                            extraColumns={extraColumns}
                            emptyState={emptyState}
                        />
                    </div>
                </div>
            )}
        </>
    )
}
