import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'

import { FeatureFlagGroupType, FeatureFlagType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { Persons } from 'scenes/persons/Persons'
import { IconDelete, IconPlus } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import { LabelInValue, LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple'
import { useDebouncedCallback } from 'use-debounce'
import { PersonLogicProps, personsLogic } from 'scenes/persons/personsLogic'
import api from 'lib/api'
import { Row } from 'antd'
import { featureFlagLogic } from './featureFlagLogic'

export const hasManualReleaseCondition = (featureFlag: FeatureFlagType, group: FeatureFlagGroupType): boolean => {
    return !!group.properties.some((property) => property.key === '$feature_enrollment/' + featureFlag.key)
}

interface FeatureProps {
    id: number
}

export function ManualReleaseTab({ id }: FeatureProps): JSX.Element {
    const logic = featureFlagLogic({ id })
    const { featureFlag } = useValues(logic)
    const { enableManualCondition } = useActions(logic)
    const [selectedPersons, setSelectedPersons] = useState<PersonType[]>([])
    const [isModalOpen, setIsModalOpen] = useState(false)

    const toggleModal = (): void => {
        setIsModalOpen(!isModalOpen)
    }

    const hasManualRelease = featureFlag.filters.groups.some((group) => hasManualReleaseCondition(featureFlag, group))

    return hasManualRelease ? (
        <div>
            <PersonList featureFlag={featureFlag} toggleModal={toggleModal} localPersons={selectedPersons} />
            <EnrollmentSelectorModal
                onAdded={(persons) => setSelectedPersons(persons)}
                featureFlag={featureFlag}
                visible={isModalOpen}
                onClose={toggleModal}
            />
        </div>
    ) : (
        <div className="mb-4 border rounded p-4">
            <div className="mb-2">
                Manual Release enables you to manually enroll users in a feature flag. Enabling this will add a static
                release condition to the feature flag.
            </div>
            <Row justify="end">
                <LemonButton type="primary" onClick={() => enableManualCondition()}>
                    Enable
                </LemonButton>
            </Row>
        </div>
    )
}

interface PersonListProps {
    featureFlag: FeatureFlagType
    toggleModal: () => void
    localPersons: PersonType[]
}

function PersonList({ featureFlag, toggleModal, localPersons = [] }: PersonListProps): JSX.Element {
    const key = '$feature_enrollment/' + featureFlag.key
    const personLogicProps: PersonLogicProps = {
        cohort: undefined,
        syncWithUrl: false,
        fixedProperties: [
            {
                key: key,
                type: PropertyFilterType.Person,
                operator: PropertyOperator.IsSet,
            },
        ],
    }
    const logic = personsLogic(personLogicProps)

    useEffect(() => {
        logic.actions.setPersons(localPersons)
    }, [localPersons])

    const optUserOut = async (person: PersonType): Promise<void> => {
        await api.persons.updateProperty(person.id as string, key, false)
        logic.actions.setPerson({ ...person, properties: { ...person.properties, [key]: false } })
    }

    const optUserIn = async (person: PersonType): Promise<void> => {
        await api.persons.updateProperty(person.id as string, key, true)
        logic.actions.setPerson({ ...person, properties: { ...person.properties, [key]: true } })
    }

    return (
        <BindLogic logic={personsLogic} props={personLogicProps}>
            <Persons
                useParentLogic={true}
                fixedProperties={[
                    {
                        key: key,
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.IsSet,
                    },
                ]}
                extraSceneActions={[
                    <LemonButton
                        key={'$feature_enrollment/' + featureFlag.key}
                        type="primary"
                        icon={<IconPlus />}
                        onClick={toggleModal}
                    >
                        Add person
                    </LemonButton>,
                ]}
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
                                    icon={<IconDelete />}
                                    status="danger"
                                    size="small"
                                />
                            ) : (
                                <LemonButton
                                    onClick={() => optUserIn(person)}
                                    icon={<IconPlus />}
                                    status="primary"
                                    size="small"
                                />
                            )
                        },
                    },
                ]}
                compact={true}
                showExportAction={false}
            />
        </BindLogic>
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
            title={'Select person to add'}
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
                <Persons
                    fixedProperties={[
                        {
                            key: key,
                            type: PropertyFilterType.Person,
                            operator: PropertyOperator.IsNotSet,
                        },
                    ]}
                    compact={true}
                    showFilters={false}
                    showExportAction={false}
                    showSearch={false}
                    useParentLogic={true}
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
