import { LemonButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'

import { PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { PersonsScene } from 'scenes/persons/Persons'
import { IconCancel, IconHelpOutline, IconPlus } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'
import { PersonLogicProps, personsLogic } from 'scenes/persons/personsLogic'
import api from 'lib/api'
import { manualReleaseLogic } from './manualReleaseLogic'

interface PersonListProps {
    localPersons: PersonType[]
}

export function ManualReleaseList({ localPersons = [] }: PersonListProps): JSX.Element {
    const { featureFlag, manualReleasePropKey } = useValues(manualReleaseLogic)
    const { toggleEnrollmentModal, toggleImplementOptInInstructionsModal } = useActions(manualReleaseLogic)

    const personLogicProps: PersonLogicProps = {
        cohort: undefined,
        syncWithUrl: false,
        fixedProperties: [
            {
                key: manualReleasePropKey,
                type: PropertyFilterType.Person,
                operator: PropertyOperator.IsSet,
            },
        ],
    }
    const logic = personsLogic(personLogicProps)

    const { persons } = useValues(logic)
    useEffect(() => {
        logic.actions.setPersons(localPersons)
    }, [localPersons])

    const optUserOut = async (person: PersonType): Promise<void> => {
        await api.persons.updateProperty(person.id as string, manualReleasePropKey, false)
        logic.actions.setPerson({ ...person, properties: { ...person.properties, [manualReleasePropKey]: false } })
    }

    const optUserIn = async (person: PersonType): Promise<void> => {
        await api.persons.updateProperty(person.id as string, manualReleasePropKey, true)
        logic.actions.setPerson({ ...person, properties: { ...person.properties, [manualReleasePropKey]: true } })
    }

    return (
        <BindLogic logic={personsLogic} props={personLogicProps}>
            <PersonsScene
                extraSceneActions={
                    persons.results.length > 0
                        ? [
                              <LemonButton
                                  key="help-button"
                                  onClick={toggleImplementOptInInstructionsModal}
                                  sideIcon={<IconHelpOutline />}
                              >
                                  Implement public opt-in
                              </LemonButton>,
                              <LemonButton
                                  key={'$feature_enrollment/' + featureFlag.key}
                                  type="primary"
                                  icon={<IconPlus />}
                                  onClick={toggleEnrollmentModal}
                              >
                                  Add person
                              </LemonButton>,
                          ]
                        : []
                }
                extraColumns={[
                    {
                        title: 'Opted In',
                        dataIndex: 'properties',
                        render: function Render(_, person: PersonType) {
                            return <span>{person.properties['$feature_enrollment/' + featureFlag.key].toString()}</span>
                        },
                    },
                    {
                        render: function Render(_, person: PersonType) {
                            return person.properties['$feature_enrollment/' + featureFlag.key] ? (
                                <LemonButton
                                    onClick={() => optUserOut(person)}
                                    icon={<IconCancel />}
                                    tooltip="Opt out"
                                    status="danger"
                                    size="small"
                                />
                            ) : (
                                <LemonButton
                                    onClick={() => optUserIn(person)}
                                    icon={<IconPlus />}
                                    status="primary"
                                    tooltip="Opt in"
                                    size="small"
                                />
                            )
                        },
                    },
                ]}
                compact={true}
                showExportAction={false}
                showFilters={false}
                showSearch={persons.results.length > 0}
                emptyState={
                    <div>
                        No manual opt-ins. Manually opted-in people will appear here. Start by{' '}
                        <a onClick={toggleEnrollmentModal}>adding people</a> or{' '}
                        <a onClick={toggleImplementOptInInstructionsModal}>implementing public opt-in</a>
                    </div>
                }
            />
        </BindLogic>
    )
}
