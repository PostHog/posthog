import { useValues, useActions, BindLogic } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Col, Popconfirm } from 'antd'
import { personsLogic } from './personsLogic'
import { CohortType, PersonPropertyFilter, PersonType } from '~/types'
import { PersonsSearch } from './PersonsSearch'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconExport } from 'lib/lemon-ui/icons'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'

interface PersonsProps {
    cohort?: CohortType['id']
    fixedProperties?: PersonPropertyFilter[]
    extraSceneActions?: JSX.Element[]
    compact?: boolean
    showFilters?: boolean
    showExportAction?: boolean
    extraColumns?: LemonTableColumn<PersonType, keyof PersonType | undefined>[]
    showSearch?: boolean
    useParentLogic?: boolean
    emptyState?: JSX.Element
}

export function Persons({
    cohort,
    fixedProperties,
    extraSceneActions,
    compact,
    showFilters,
    showExportAction,
    extraColumns,
    showSearch,
    emptyState,
    useParentLogic = false,
}: PersonsProps = {}): JSX.Element {
    if (useParentLogic) {
        return (
            <PersonsScene
                extraSceneActions={extraSceneActions}
                compact={compact}
                showFilters={showFilters}
                showExportAction={showExportAction}
                extraColumns={extraColumns}
                showSearch={showSearch}
                emptyState={emptyState}
            />
        )
    }

    return (
        <BindLogic
            logic={personsLogic}
            props={{ cohort: cohort, syncWithUrl: !cohort && !fixedProperties, fixedProperties }}
        >
            <PersonsScene
                extraSceneActions={extraSceneActions}
                compact={compact}
                showFilters={showFilters}
                showExportAction={showExportAction}
                extraColumns={extraColumns}
                showSearch={showSearch}
                emptyState={emptyState}
            />
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

    return (
        <div className="persons-list">
            <div className="space-y-2">
                <div className="flex justify-between items-center gap-2">
                    {showSearch ? (
                        <Col>
                            <PersonsSearch />
                        </Col>
                    ) : (
                        <Col>
                            <div />
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
                                        To export more, please use <a href={apiDocsURL}>the API</a>. Do you want to
                                        export by CSV?
                                    </>
                                }
                                onConfirm={() => triggerExport(exporterProps[0])}
                            >
                                <LemonButton type="secondary" icon={<IconExport style={{ color: 'var(--primary)' }} />}>
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
                    emptyState={emptyState}
                    people={persons.results}
                    loading={personsLoading}
                    hasPrevious={!!persons.previous}
                    hasNext={!!persons.next}
                    loadPrevious={() => loadPersons(persons.previous)}
                    loadNext={() => loadPersons(persons.next)}
                    compact={compact}
                    extraColumns={extraColumns}
                />
            </div>
        </div>
    )
}
