import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import api from 'lib/api'
import { LabelInValue, LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple'
import { IconPlus } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import { PersonsScene } from 'scenes/persons/Persons'
import { PersonLogicProps, personsLogic } from 'scenes/persons/personsLogic'
import { useDebouncedCallback } from 'use-debounce'
import { FeatureFlagType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'

interface EnrollmentSelectorProps {
    featureFlag: FeatureFlagType
    visible: boolean
    onClose: () => void
    onAdded: (persons: PersonType[]) => void
}

export function EnrollmentSelectorModal({
    featureFlag,
    visible,
    onClose,
    onAdded,
}: EnrollmentSelectorProps): JSX.Element {
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
