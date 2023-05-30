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
import { FilterLogicalOperator, SurveyQuestion, SurveyType } from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { IconErrorOutline, IconPlus, IconPlusMini } from 'lib/lemon-ui/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { Query } from '~/queries/Query/Query'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { surveysLogic } from './surveysLogic'

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
    return (
        <div>{!id ? <LemonSkeleton /> : <>{showSurveyForm ? <SurveyForm id={id} /> : <SurveyView id={id} />}</>}</div>
    )
}

export function SurveyForm({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, isEditingSurvey, propertySelectErrors } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey, updateTargetingFlagFilters, addConditionSet } = useActions(surveyLogic)

    return (
        <Form formKey="survey" logic={surveyLogic} className="space-y-4" enableFormOnSubmit>
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
                    <LemonSelect
                        dropdownMaxContentWidth
                        data-attr="survey-type"
                        options={[{ label: 'Popover', value: SurveyType.Popover }]}
                    />
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
                {survey.questions.map((question: SurveyQuestion, index: number) => (
                    <Group name={`questions.${index}`} key={index}>
                        <Field name="question" label="Question">
                            <LemonInput value={question.question} />
                        </Field>
                    </Group>
                ))}
                <PureField label="Targeting">
                    <span className="text-muted">
                        Choose when the survey appears based on url, selector, and user properties.
                    </span>
                    <LemonDivider />
                    <Field name="conditions">
                        {({ value, onChange }) => (
                            <>
                                <PureField label="Url">
                                    <LemonInput
                                        value={value?.url}
                                        onChange={(urlVal) => onChange({ ...value, url: urlVal })}
                                    />
                                </PureField>
                                <LogicalRowDivider logicalOperator={FilterLogicalOperator.And} />
                                <PureField label="Selector">
                                    <LemonInput
                                        value={value?.selector}
                                        onChange={(selectorVal) => onChange({ ...value, selector: selectorVal })}
                                    />
                                </PureField>
                            </>
                        )}
                    </Field>
                    <LogicalRowDivider logicalOperator={FilterLogicalOperator.And} />
                    {(id === 'new'
                        ? survey.targeting_flag_filters?.groups || []
                        : survey.targeting_flag?.filters?.groups || []
                    ).map((group, index) => (
                        <>
                            {index > 0 && <div className="text-primary-alt font-semibold text-xs ml-2">OR</div>}
                            <div className="border rounded p-4">
                                <div className="mb-2">
                                    Matching <b>users</b> against the criteria
                                </div>
                                <div>
                                    <PropertyFilters
                                        orFiltering={true}
                                        pageKey={`survey-${id}-targeting-${index}`}
                                        propertyFilters={group.properties}
                                        logicalRowDivider
                                        addButton={
                                            <LemonButton icon={<IconPlusMini />} sideIcon={null} noPadding>
                                                Add condition
                                            </LemonButton>
                                        }
                                        onChange={(properties) => updateTargetingFlagFilters(index, properties)}
                                        taxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.Cohorts,
                                        ]}
                                        hasRowOperator={false}
                                        sendAllKeyUpdates
                                        errorMessages={
                                            propertySelectErrors?.[index]?.properties?.some(
                                                (message) => !!message.value
                                            )
                                                ? propertySelectErrors[index].properties.map((message, index) => {
                                                      return message.value ? (
                                                          <div
                                                              key={index}
                                                              className="text-danger flex items-center gap-1 text-sm"
                                                          >
                                                              <IconErrorOutline className="text-xl" /> {message.value}
                                                          </div>
                                                      ) : (
                                                          <></>
                                                      )
                                                  })
                                                : null
                                        }
                                    />
                                </div>
                            </div>
                        </>
                    ))}
                    <LemonButton type="secondary" className="mt-0" onClick={addConditionSet} icon={<IconPlus />}>
                        Add condition set
                    </LemonButton>
                </PureField>
            </div>
            <LemonDivider />
            <div className="flex items-center gap-2 justify-end">
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
                <LemonButton type="primary" data-attr="save-feature-flag" htmlType="submit" loading={surveyLoading}>
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, isSurveyRunning, dataTableQuery } = useValues(surveyLogic)
    const { editingSurvey, updateSurvey } = useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)

    const [tabKey, setTabKey] = useState('overview')

    return (
        <div>
            <PageHeader
                title={survey.name}
                buttons={
                    <div className="flex items-center gap-2">
                        <More
                            overlay={
                                <>
                                    <LemonButton data-attr="edit-survey" fullWidth onClick={() => editingSurvey(true)}>
                                        Edit
                                    </LemonButton>
                                    <LemonDivider />
                                    <LemonButton status="danger" onClick={() => deleteSurvey(id)}>
                                        Delete survey
                                    </LemonButton>
                                </>
                            }
                        />
                        <LemonDivider vertical />
                        {!isSurveyRunning ? (
                            <LemonButton type="primary" onClick={() => {}}>
                                Launch
                            </LemonButton>
                        ) : (
                            <LemonButton type="primary" onClick={() => {}}>
                                Stop
                            </LemonButton>
                        )}
                    </div>
                }
                caption={
                    <>
                        {survey && !!survey.description && (
                            <EditableField
                                multiline
                                name="description"
                                value={survey.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) => updateSurvey({ id: id, description: value })}
                                saveOnBlur={true}
                                compactButtons
                            />
                        )}
                    </>
                }
            />
            <LemonTabs
                activeKey={tabKey}
                onChange={(key) => setTabKey(key)}
                tabs={[
                    {
                        content: (
                            <div className="flex flex-col">
                                <span className="card-secondary mt-4">Type</span>
                                <span>{SurveyType.Popover}</span>
                                <span className="card-secondary mt-4">Questions</span>
                                <span />
                            </div>
                        ),
                        key: 'overview',
                        label: 'Overview',
                    },
                    survey.start_date
                        ? {
                              content: (
                                  <div>
                                      <div className="flex flex-row gap-4">
                                          <div className="border rounded p-4">
                                              <span>Impressions</span>
                                              <h2>257</h2>
                                          </div>
                                          <div className="border rounded p-4">
                                              <span>Started</span>
                                              <h2>78</h2>
                                          </div>
                                          <div className="border rounded p-4">
                                              <span>Completed</span>
                                              <h2>55</h2>
                                          </div>
                                      </div>
                                      <LemonDivider />
                                      <Query query={dataTableQuery} />
                                  </div>
                              ),
                              key: 'results',
                              label: 'Results',
                          }
                        : null,
                ]}
            />
        </div>
    )
}
