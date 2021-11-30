import React from 'react'
import { useValues, useActions, BindLogic } from 'kea'
import { PersonsTable } from './PersonsTable'
import { Button, Row } from 'antd'
import { ExportOutlined, ClockCircleFilled } from '@ant-design/icons'
import { PersonLogicProps, personsLogic } from './personsLogic'
import { CohortType } from '~/types'
import { PersonsSearch } from './PersonsSearch'
import { SceneExport } from 'scenes/sceneTypes'
import { PersonPageHeader } from './PersonPageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LinkButton } from 'lib/components/LinkButton'
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

    return (
        <BindLogic logic={personsLogic} props={personsLogicProps}>
            <div className="persons-list">
                <PersonPageHeader hideGroupTabs={!!cohort} />
                <Row align="middle" justify="space-between" className="mb" style={{ gap: '0.75rem' }}>
                    <PersonsSearch autoFocus={!cohort} />
                    <div>
                        {cohort ? (
                            <LinkButton
                                to={`/sessions?${toParams({
                                    properties: [{ key: 'id', value: cohort.id, type: 'cohort' }],
                                })}`}
                                target="_blank"
                            >
                                <ClockCircleFilled /> View sessions
                            </LinkButton>
                        ) : null}
                        <Button
                            type="default"
                            icon={<ExportOutlined />}
                            href={'/api/person.csv' + (listFilters.cohort ? '?cohort=' + listFilters.cohort : '')}
                            style={{ marginLeft: 8 }}
                        >
                            Export
                        </Button>
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
