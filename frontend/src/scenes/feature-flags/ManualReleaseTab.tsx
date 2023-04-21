import { LemonButton, LemonCollapse, LemonModal } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'

import { FeatureFlagType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { PersonsScene } from 'scenes/persons/Persons'
import { IconCancel, IconHelpOutline, IconPlus } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import { LabelInValue, LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple'
import { useDebouncedCallback } from 'use-debounce'
import { PersonLogicProps, personsLogic } from 'scenes/persons/personsLogic'
import api from 'lib/api'
import { Row } from 'antd'
import { manualReleaseLogic } from './manualReleaseLogic'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

interface FeatureProps {
    id: number
}

function FeatureEnrollInstructions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.updateFeaturePreviewEnrollment("${featureFlag.key}", true)
`}
        </CodeSnippet>
    )
}

function FeatureUnenrollInstructions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.updateFeaturePreviewEnrollment("${featureFlag.key}", false)
`}
        </CodeSnippet>
    )
}

function RetrievePreviewsInstructions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.getFeaturePreviews()
// Example response:
// {
//     flagKey: '${featureFlag.key}',
// }
`}
        </CodeSnippet>
    )
}

export function ManualReleaseTab({ id }: FeatureProps): JSX.Element {
    const [selectedPersons, setSelectedPersons] = useState<PersonType[]>([])

    const logic = manualReleaseLogic({ id })
    const { implementOptInInstructionsModal, enrollmentModal, featureFlag, hasManualRelease } = useValues(logic)
    const { toggleImplementOptInInstructionsModal, toggleEnrollmentModal, enableManualCondition } = useActions(logic)

    return hasManualRelease ? (
        <BindLogic logic={manualReleaseLogic} props={{ id }}>
            <PersonList localPersons={selectedPersons} />
            <EnrollmentSelectorModal
                onAdded={(persons) => setSelectedPersons(persons)}
                featureFlag={featureFlag}
                visible={enrollmentModal}
                onClose={toggleEnrollmentModal}
            />
            <InstructionsModal
                featureFlag={featureFlag}
                visible={implementOptInInstructionsModal}
                onClose={toggleImplementOptInInstructionsModal}
            />
        </BindLogic>
    ) : (
        <div className="flex justify-center">
            <div className="mb-4 border rounded p-4 max-w-160">
                <div>
                    <b>Enable Manual Release for this Feature flag</b>
                </div>
                <div className="mb-3">
                    Manual Release conditions are the easiest way for you to have flexible control over who gets exposed
                    to your feature flags. With manual release conditions, you can:
                </div>

                <div className="mb-1 mt-2">
                    - Add and remove users from a feature flag without needing to specify property conditions
                </div>

                <div className="mb-2">
                    - Implement opt-in functionality for your users to self-determine if they would like to be exposed
                    to a feature flag
                </div>

                <Row justify="end">
                    <LemonButton
                        disabledReason={
                            featureFlag.filters.multivariate ? 'Beta only available for boolean flags' : null
                        }
                        type="primary"
                        onClick={enableManualCondition}
                    >
                        Enable
                    </LemonButton>
                </Row>
            </div>
        </div>
    )
}

interface PersonListProps {
    localPersons: PersonType[]
}

function PersonList({ localPersons = [] }: PersonListProps): JSX.Element {
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

interface InnstructionsModalProps {
    featureFlag: FeatureFlagType
    visible: boolean
    onClose: () => void
}

function InstructionsModal({ onClose, visible, featureFlag }: InnstructionsModalProps): JSX.Element {
    return (
        <LemonModal title="How to implement opt-in feature flags" isOpen={visible} onClose={onClose} width={640}>
            <div>
                <span>
                    Implement manual release condition toggles to give your users the ability choose which features they
                    want to try
                </span>
                <LemonCollapse
                    className="mt-2"
                    defaultActiveKey="1"
                    panels={[
                        {
                            key: '1',
                            header: 'Option 1: Custom implementation',
                            content: (
                                <div>
                                    <b>Opt user in</b>
                                    <div>
                                        <FeatureEnrollInstructions featureFlag={featureFlag} />
                                    </div>

                                    <b>Opt user out</b>
                                    <div>
                                        <FeatureUnenrollInstructions featureFlag={featureFlag} />
                                    </div>

                                    <b>Retrieve Previews</b>
                                    <div>
                                        <RetrievePreviewsInstructions featureFlag={featureFlag} />
                                    </div>
                                </div>
                            ),
                        },
                        {
                            key: '2',
                            header: 'Option 2: Widget Site App',
                            content: <div />,
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}

interface EnrollmentSelectorProps {
    featureFlag: FeatureFlagType
    visible: boolean
    onClose: () => void
    onAdded: (persons: PersonType[]) => void
}

function EnrollmentSelectorModal({ featureFlag, visible, onClose, onAdded }: EnrollmentSelectorProps): JSX.Element {
    const personLogicProps: PersonLogicProps = {
        cohort: undefined,
        syncWithUrl: false,
        fixedProperties: [
            {
                key: '$feature_enrollment/' + featureFlag.key,
                type: PropertyFilterType.Person,
                operator: PropertyOperator.IsNotSet,
            },
        ],
    }
    const logic = personsLogic(personLogicProps)

    const { loadPersons, setListFilters } = useActions(logic)
    const { listFilters } = useValues(logic)
    const [searchTerm, setSearchTerm] = useState('')
    const [selected, setSelected] = useState<PersonType[]>([])
    const [selectedLabelValue, setSelectedLabelValue] = useState<LabelInValue[]>([])
    const [confirmLoading, setConfirmLoading] = useState(false)
    const key = '$feature_enrollment/' + featureFlag.key

    const loadPersonsDebounced = useDebouncedCallback(loadPersons, 800)

    useEffect(() => {
        setSearchTerm(listFilters.search || '')
    }, [])

    useEffect(() => {
        setListFilters({ search: searchTerm || undefined })
        loadPersonsDebounced()
    }, [searchTerm])

    useEffect(() => {
        setSelectedLabelValue(selected.map((item) => ({ value: item.id as string, label: item.name })))
    }, [selected])

    const onConfirm = async (): Promise<void> => {
        setConfirmLoading(true)
        await Promise.all(selected.map((item) => api.persons.updateProperty(item.id as string, key, true)))
        setConfirmLoading(false)
        onClose()

        // Need to store local copy because updating person properties uses ingestion pipeline which may lag
        const hydrated = selected.map((item) => ({ ...item, properties: { ...item.properties, [key]: true } }))
        onAdded(hydrated)
    }

    return (
        <LemonModal
            title={'Select people'}
            isOpen={visible}
            onClose={onClose}
            width={560}
            footer={
                <LemonButton type="primary" loading={confirmLoading} onClick={onConfirm}>
                    Confirm
                </LemonButton>
            }
        >
            <BindLogic logic={personsLogic} props={personLogicProps}>
                <div className="mb-3">
                    <span>People added here will be manually opted-in to the feature flag</span>
                </div>
                <h5 className="mt-2">People</h5>
                <div className="flex gap-2">
                    <div className="flex-1">
                        <LemonSelectMultiple
                            placeholder="Search for persons to add…"
                            labelInValue
                            value={selectedLabelValue}
                            loading={false}
                            onSearch={setSearchTerm}
                            onChange={(newValues: LabelInValue[]) => {
                                const newSelected = selected.filter((person) =>
                                    newValues.find((item) => item.value === person.id)
                                )
                                setSelected(newSelected)
                            }}
                            filterOption={true}
                            mode="multiple"
                            data-attr="feature-persons-emails"
                            options={[]}
                        />
                    </div>
                </div>
                <PersonsScene
                    compact={true}
                    showFilters={false}
                    showExportAction={false}
                    showSearch={false}
                    extraColumns={[
                        {
                            render: function Render(_, person: PersonType) {
                                const isSelected = selected.some((item) => item.id === person.id)
                                return (
                                    <LemonButton
                                        onClick={() => {
                                            if (isSelected) {
                                                setSelected(selected.filter((item) => item.id !== person.id))
                                            } else {
                                                person.id && setSelected([...selected, person])
                                            }
                                        }}
                                        icon={<IconPlus />}
                                        size="small"
                                        type={isSelected ? 'primary' : 'secondary'}
                                    />
                                )
                            },
                        },
                    ]}
                />
            </BindLogic>
        </LemonModal>
    )
}
