import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { Field, PureField } from 'lib/forms/Field'
import { SceneExport } from 'scenes/sceneTypes'
import { featureLogic } from './featureLogic'
import { Field as KeaField, Form } from 'kea-forms'
import { FeatureType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { urls } from 'scenes/urls'
import { Persons } from 'scenes/persons/Persons'
import { IconDelete, IconFlag, IconPlus } from 'lib/lemon-ui/icons'
import { router } from 'kea-router'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useEffect, useState } from 'react'
import { Popover } from 'lib/lemon-ui/Popover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { LabelInValue, LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple'
import { useDebouncedCallback } from 'use-debounce'
import { PersonLogicProps, personsLogic } from 'scenes/persons/personsLogic'
import api from 'lib/api'
import clsx from 'clsx'

export const scene: SceneExport = {
    component: Feature,
    logic: featureLogic,
    paramsToProps: ({ params: { id } }): typeof featureLogic['props'] => ({
        id,
    }),
}

function FeatureEnrollInstructions({ feature }: { feature: FeatureType }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.updateFeaturePreviewEnrollment("${feature.feature_flag.key}", true)
`}
        </CodeSnippet>
    )
}

function FeatureUnenrollInstructions({ feature }: { feature: FeatureType }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.updateFeaturePreviewEnrollment("${feature.feature_flag.key}", false)
`}
        </CodeSnippet>
    )
}

function RetrievePreviewsInstructions({ feature }: { feature: FeatureType }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.getFeaturePreviews()
// Example response:
// {
//     name: '${feature.name}',
//     stage: '${feature.stage}',
//     flagKey: '${feature.feature_flag.key}',
// }
`}
        </CodeSnippet>
    )
}

export function Feature(): JSX.Element {
    const { feature, featureLoading, isFeatureSubmitting, isEditingFeature } = useValues(featureLogic)
    const { submitFeatureRequest, cancel, editFeature } = useActions(featureLogic)
    const [selectedPersons, setSelectedPersons] = useState<PersonType[]>([])

    const [isModalOpen, setIsModalOpen] = useState(false)

    const toggleModal = (): void => {
        setIsModalOpen(!isModalOpen)
    }

    console.log(feature)
    return (
        <Form formKey="feature" logic={featureLogic}>
            <PageHeader
                title={isEditingFeature && !('id' in feature) ? 'New Feature' : feature.name}
                buttons={
                    !featureLoading ? (
                        isEditingFeature ? (
                            <>
                                <LemonButton
                                    type="secondary"
                                    onClick={() => cancel()}
                                    disabledReason={isFeatureSubmitting ? 'Saving…' : undefined}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    onClick={() => {
                                        submitFeatureRequest(feature)
                                    }}
                                    loading={isFeatureSubmitting}
                                >
                                    Save
                                </LemonButton>
                            </>
                        ) : (
                            <LemonButton
                                type="secondary"
                                htmlType="submit"
                                onClick={() => {
                                    editFeature(true)
                                }}
                                loading={false}
                            >
                                Edit
                            </LemonButton>
                        )
                    ) : undefined
                }
                delimited
            />
            <div className={clsx('flex', 'flex-row', 'gap-4', isEditingFeature ? 'max-w-160' : null)}>
                <div className="flex flex-col flex-1 gap-4">
                    {isEditingFeature && !('id' in feature) && (
                        <Field name="name" label="Name">
                            <LemonInput data-attr="feature-name" />
                        </Field>
                    )}
                    {'feature_flag' in feature ? (
                        <PureField label="Connected Feature flag">
                            <div>
                                <LemonButton
                                    type="secondary"
                                    onClick={() =>
                                        feature.feature_flag &&
                                        router.actions.push(urls.featureFlag(feature.feature_flag.id))
                                    }
                                    icon={<IconFlag />}
                                >
                                    {feature.feature_flag.key}
                                </LemonButton>
                            </div>
                        </PureField>
                    ) : (
                        <Field
                            name="feature_flag_id"
                            label="Link feature flag"
                            info={<>A feature flag will be generated from feature name by default</>}
                        >
                            {({ value, onChange }) => (
                                <div>
                                    <FlagSelector value={value} onChange={onChange} />
                                </div>
                            )}
                        </Field>
                    )}
                    {isEditingFeature ? (
                        <KeaField name="stage" label={<h4 className="font-semibold">Stage</h4>}>
                            {({ value, onChange }) => (
                                <div>
                                    <LemonSelect
                                        value={value}
                                        onChange={onChange}
                                        options={[
                                            {
                                                label: 'Alpha',
                                                value: 'alpha',
                                            },
                                            {
                                                label: 'Beta',
                                                value: 'beta',
                                            },
                                            {
                                                label: 'General Availability',
                                                value: 'general-availability',
                                            },
                                        ]}
                                    />
                                </div>
                            )}
                        </KeaField>
                    ) : (
                        <div className="mb-2">
                            <b>Stage</b>
                            <div>
                                <LemonTag type="highlight" className="mt-2 uppercase">
                                    {feature.stage}
                                </LemonTag>
                            </div>
                        </div>
                    )}
                    {isEditingFeature ? (
                        <Field name="description" label="Description" showOptional>
                            <LemonTextArea
                                className="ph-ignore-input"
                                placeholder="Help your users understand the feature"
                            />
                        </Field>
                    ) : (
                        <div className="mb-2">
                            <b>Description</b>
                            <div>
                                {feature.description ? (
                                    feature.description
                                ) : (
                                    <span className="text-muted">No description</span>
                                )}
                            </div>
                        </div>
                    )}
                    {isEditingFeature ? (
                        <Field name="documentation_url" label="Documentation URL" showOptional>
                            <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
                        </Field>
                    ) : (
                        <div className="mb-2">
                            <b>Documentation Url</b>
                            <div>
                                {feature.documentation_url ? (
                                    feature.documentation_url
                                ) : (
                                    <span className="text-muted">No documentation url</span>
                                )}
                            </div>
                        </div>
                    )}
                </div>
                {!isEditingFeature && 'id' in feature && feature.stage !== 'general-availability' && (
                    <div className="border rounded p-3 w-1/2 max-w-160">
                        <span>
                            <b>Integrate feature previews</b>
                        </span>
                        <div>
                            <span>
                                Use these functions in your product to enable your users to opt-in/opt-out of feature
                                previews
                            </span>
                        </div>
                        <LemonDivider className="my-4" />

                        <b>Opt user in</b>
                        <div>
                            <FeatureEnrollInstructions feature={feature} />
                        </div>

                        <b>Opt user out</b>
                        <div>
                            <FeatureUnenrollInstructions feature={feature} />
                        </div>

                        <b>Retrieve Previews</b>
                        <div>
                            <RetrievePreviewsInstructions feature={feature} />
                        </div>
                    </div>
                )}
            </div>
            {!isEditingFeature && 'id' in feature && (
                <PersonList feature={feature} toggleModal={toggleModal} localPersons={selectedPersons} />
            )}
            {!isEditingFeature && 'id' in feature && (
                <EnrollmentSelectorModal
                    onAdded={(persons) => setSelectedPersons(persons)}
                    feature={feature}
                    visible={isModalOpen}
                    onClose={toggleModal}
                />
            )}
        </Form>
    )
}

interface FlagSelectorProps {
    value: number | undefined
    onChange: (value: any) => void
}

function FlagSelector({ value, onChange }: FlagSelectorProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    const { featureFlag } = useValues(featureFlagLogic({ id: value || 'link' }))

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        groupType: TaxonomicFilterGroupType.FeatureFlags,
        value,
        onChange: (_, __, item) => {
            'id' in item && item.id && onChange(item.id)
            setVisible(false)
        },
        taxonomicGroupTypes: [TaxonomicFilterGroupType.FeatureFlags],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
        taxonomicFilterLogicKey: 'universalSearch',
    }

    return (
        <Popover
            overlay={<TaxonomicFilter {...taxonomicFilterLogicProps} />}
            visible={visible}
            placement="right-start"
            fallbackPlacements={['bottom']}
            onClickOutside={() => setVisible(false)}
        >
            <LemonButton type="secondary" onClick={() => setVisible(!visible)}>
                {!!featureFlag.key ? featureFlag.key : 'Select flag'}
            </LemonButton>
        </Popover>
    )
}

interface PersonListProps {
    feature: FeatureType
    toggleModal: () => void
    localPersons: PersonType[]
}

function PersonList({ feature, toggleModal, localPersons = [] }: PersonListProps): JSX.Element {
    const key = '$feature_enrollment/' + feature.feature_flag.key
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
            <LemonDivider className="my-4" />
            <h3 className="text-xl font-semibold my-4">Persons</h3>
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
                        key={'$feature_enrollment/' + feature.feature_flag.key}
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
                            return (
                                <span>
                                    {person.properties['$feature_enrollment/' + feature.feature_flag.key].toString()}
                                </span>
                            )
                        },
                    },
                    {
                        render: function Render(_, person: PersonType) {
                            return person.properties['$feature_enrollment/' + feature.feature_flag.key] ? (
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
    feature: FeatureType
    visible: boolean
    onClose: () => void
    onAdded: (persons: PersonType[]) => void
}

function EnrollmentSelectorModal({ feature, visible, onClose, onAdded }: EnrollmentSelectorProps): JSX.Element {
    const personLogicProps: PersonLogicProps = {
        cohort: undefined,
        syncWithUrl: false,
        fixedProperties: [
            {
                key: '$feature_enrollment/' + feature.feature_flag.key,
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
    const key = '$feature_enrollment/' + feature.feature_flag.key

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
