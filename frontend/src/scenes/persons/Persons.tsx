import React from 'react'
import { useValues, useActions, BindLogic } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Button, Popconfirm, Row } from 'antd'
import { ExportOutlined } from '@ant-design/icons'
import { PersonLogicProps, personsLogic } from './personsLogic'
import { CohortType } from '~/types'
import { PersonsSearch } from './PersonsSearch'
import { SceneExport } from 'scenes/sceneTypes'
import { PersonPageHeader } from './PersonPageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { toParams } from 'lib/utils'

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
    const { loadPersons, setListFilters } = useActions(personsLogic(personsLogicProps))
    const { persons, listFilters, personsLoading } = useValues(personsLogic(personsLogicProps))
    const personHref = cohort?.id ? `/api/cohort/${cohort.id}/persons.csv?` : '/api/person.csv?' + toParams(listFilters)

    return (
        <BindLogic logic={personsLogic} props={personsLogicProps}>
            <div className="persons-list">
                <PersonPageHeader hideGroupTabs={!!cohort} />
                <Row align="middle" justify="space-between" className="mb" style={{ gap: '0.75rem' }}>
                    <PersonsSearch autoFocus={!cohort} />
                    <div>
                        <Popconfirm
                            title={
                                <>
                                    Exporting by csv is limited to 10,000 users.
                                    <br />
                                    To return more, please use{' '}
                                    <a href="https://posthog.com/docs/api/persons">the API</a>. Do you want to export by
                                    CSV?
                                </>
                            }
                            onConfirm={() => {
                                window.location.href = personHref
                            }}
                        >
                            <Button
                                type="default"
                                icon={<ExportOutlined />}
                                href={personHref}
                                style={{ marginLeft: 8 }}
                            >
                                {listFilters.properties && listFilters.properties.length > 0 ? (
                                    <>
                                        Export (<strong>{listFilters.properties.length}</strong> filter)
                                    </>
                                ) : (
                                    'Export'
                                )}
                            </Button>
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
