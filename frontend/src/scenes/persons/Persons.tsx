import React from 'react'
import { useValues, useActions, BindLogic } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Popconfirm, Row } from 'antd'
import { PersonLogicProps, personsLogic } from './personsLogic'
import { CohortType } from '~/types'
import { PersonsSearch } from './PersonsSearch'
import { SceneExport } from 'scenes/sceneTypes'
import { PersonPageHeader } from './PersonPageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/components/LemonButton'
import { IconExport } from 'lib/components/icons'

export const scene: SceneExport = {
    component: Persons,
    logic: personsLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}
interface PersonsProps {
    cohort?: CohortType
}

export function Persons({ cohort }: PersonsProps = {}): JSX.Element {
    const personsLogicProps: PersonLogicProps = { cohort: cohort?.id, syncWithUrl: !cohort }
    const { loadPersons, setListFilters, exportCsv } = useActions(personsLogic(personsLogicProps))
    const { persons, listFilters, personsLoading, exportUrl } = useValues(personsLogic(personsLogicProps))

    return (
        <BindLogic logic={personsLogic} props={personsLogicProps}>
            <div className="persons-list">
                <PersonPageHeader hideGroupTabs={!!cohort} />
                <Row align="middle" justify="space-between" className="mb-05" style={{ gap: '0.75rem' }}>
                    <PersonsSearch autoFocus={!cohort} />
                    <div>
                        <Popconfirm
                            placement="topRight"
                            title={
                                <>
                                    Exporting by csv is limited to 10,000 users.
                                    <br />
                                    To return more, please use{' '}
                                    <a href="https://posthog.com/docs/api/persons">the API</a>. Do you want to export by
                                    CSV?
                                </>
                            }
                            onConfirm={exportCsv}
                        >
                            {exportUrl && (
                                <LemonButton type="secondary" icon={<IconExport style={{ color: 'var(--primary)' }} />}>
                                    {listFilters.properties && listFilters.properties.length > 0 ? (
                                        <div style={{ display: 'block' }}>
                                            Export (<strong>{listFilters.properties.length}</strong> filter)
                                        </div>
                                    ) : (
                                        'Export'
                                    )}
                                </LemonButton>
                            )}
                        </Popconfirm>
                    </div>
                </Row>
                <PropertyFilters
                    pageKey="persons-list-page"
                    propertyFilters={listFilters.properties}
                    onChange={(properties) => {
                        setListFilters({ properties })
                        loadPersons()
                    }}
                    endpoint="person"
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]}
                    showConditionBadge
                />
                <PersonsTable
                    people={persons.results}
                    loading={personsLoading}
                    hasPrevious={!!persons.previous}
                    hasNext={!!persons.next}
                    loadPrevious={() => loadPersons(persons.previous)}
                    loadNext={() => loadPersons(persons.next)}
                />
            </div>
        </BindLogic>
    )
}
