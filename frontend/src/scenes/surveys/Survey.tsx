import { SceneExport } from 'scenes/sceneTypes'
import { surveyLogic } from './surveyLogic'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Field, PureField } from 'lib/forms/Field'
import { SurveyType } from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { IconPlusMini } from 'lib/lemon-ui/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export const scene: SceneExport = {
    component: Survey,
    logic: surveyLogic,
    paramsToProps: ({ params: { id } }): (typeof surveyLogic)['props'] => ({
        id: id,
    }),
}

export function Survey({ id }: { id?: string } = {}): JSX.Element {
    const { isEditingSurvey } = useValues(surveyLogic)
    const showSurveyForm = id === 'new' || isEditingSurvey
    return <div>{!id ? <LemonSkeleton /> : <>{showSurveyForm ? <SurveyForm id={id} /> : <SurveyView />}</>}</div>
}

export function SurveyForm({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, isEditingSurvey } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey } = useActions(surveyLogic)
    return (
        <Form formKey="survey" logic={surveyLogic} className="space-y-4">
            <PageHeader
                title={id === 'new' ? 'New survey' : survey.name}
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-survey"
                            type="secondary"
                            loading={surveyLoading}
                            onClick={() => {
                                if (isEditingSurvey) {
                                    editingSurvey(false)
                                    loadSurvey()
                                } else {
                                    router.actions.push(urls.surveys())
                                }
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-feature-flag"
                            htmlType="submit"
                            loading={surveyLoading}
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            />
            <LemonDivider />
            <div className="flex flex-col gap-2 max-w-160">
                <Field name="name" label="Name">
                    <LemonInput data-attr="survey-name" />
                </Field>
                <Field name="description" label="Description">
                    <LemonTextArea data-attr="survey-description" />
                </Field>
                <Field name="type" label="Type">
                    <LemonSelect dropdownMaxContentWidth data-attr="survey-type" options={[{ label: 'Popover', value: SurveyType.Popover }]} />
                </Field>
                <Field
                    name="linked_flag_id"
                    label="Link feature flag (optional)"
                    info={<>Feature you want to connect this survey to.</>}
                >
                    {({ value, onChange }) => (
                        <div>
                            <FlagSelector value={value} onChange={onChange} />
                        </div>
                    )}
                </Field>
                {survey.questions.map((question, index) => (
                    <Group name={`questions.${index}`} key={index}>
                        <Field name="question" label="Question">
                            <LemonInput />
                        </Field>
                    </Group>
                ))}
                <PureField label="Targeting">
                <LemonDivider />
                    <Group name="conditions">
                        <Field name="url" label="URL">
                            <LemonInput />
                        </Field>
                        <Field name="selector" label="selector">
                            <LemonInput />
                        </Field>
                    </Group>
                    <div>
                        <>
                            Matching <b>users</b> against the criteria
                        </>
                        <div>
                            <PropertyFilters
                                orFiltering={true}
                                pageKey={`survey-${survey.id}-targeting`}
                                propertyFilters={survey.targeting_flag?.filters?.groups[0].properties}
                                logicalRowDivider
                                addButton={
                                    <LemonButton icon={<IconPlusMini />} sideIcon={null} noPadding>
                                        Add condition
                                    </LemonButton>
                                }
                                onChange={(properties) => { }}
                                // updateConditionSet(index, undefined, properties)}
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]}
                                hasRowOperator={false}
                                sendAllKeyUpdates
                            // errorMessages={
                            //     propertySelectErrors?.[index]?.properties?.some((message) => !!message.value)
                            //         ? propertySelectErrors[index].properties.map((message, index) => {
                            //             return message.value ? (
                            //                 <div
                            //                     key={index}
                            //                     className="text-danger flex items-center gap-1 text-sm"
                            //                 >
                            //                     <IconErrorOutline className="text-xl" /> {message.value}
                            //                 </div>
                            //             ) : (
                            //                 <></>
                            //             )
                            //         })
                            //         : null
                            // }
                            />
                        </div>
                    </div>
                </PureField>
            </div>
        </Form>
    )
}

export function SurveyView(): JSX.Element {
    return <div>survey view</div>
}
