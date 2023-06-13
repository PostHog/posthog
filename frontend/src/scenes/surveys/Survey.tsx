import { SceneExport } from 'scenes/sceneTypes'
import { surveyLogic } from './surveyLogic'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTextArea, Link } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Field, PureField } from 'lib/forms/Field'
import { FilterLogicalOperator, SurveyQuestion, SurveyType } from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { IconCancel, IconDelete, IconErrorOutline, IconPlus, IconPlusMini, IconSubArrowRight } from 'lib/lemon-ui/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { Query } from '~/queries/Query/Query'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useEffect, useState } from 'react'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { surveysLogic } from './surveysLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { cohortsModel } from '~/models/cohortsModel'
import { TZLabel } from 'lib/components/TZLabel'

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
    const { loadSurvey, editingSurvey, updateTargetingFlagFilters, removeConditionSet, addConditionSet } =
        useActions(surveyLogic)

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
                <Field name="description" label="Description (optional)">
                    <LemonTextArea data-attr="survey-description" />
                </Field>
                <Field name="type" label="Type" className="w-max">
                    <LemonSelect data-attr="survey-type" options={[{ label: 'Popover', value: SurveyType.Popover }]} />
                </Field>
                <Field
                    name="linked_flag_id"
                    label="Link feature flag (optional)"
                    info={<>Feature you want to connect this survey to.</>}
                >
                    {({ value, onChange }) => (
                        <div className="flex">
                            <FlagSelector value={value} onChange={onChange} />
                            {value && (
                                <LemonButton
                                    className="ml-2"
                                    icon={<IconCancel />}
                                    size="small"
                                    status="stealth"
                                    onClick={() => onChange(undefined)}
                                    aria-label="close"
                                />
                            )}
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
                <PureField label="Targeting (optional)" className="mt-4">
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
                                        placeholder="ex: https://app.posthog.com"
                                    />
                                </PureField>
                                <LogicalRowDivider logicalOperator={FilterLogicalOperator.And} />
                                <PureField label="Selector">
                                    <LemonInput
                                        value={value?.selector}
                                        onChange={(selectorVal) => onChange({ ...value, selector: selectorVal })}
                                        placeholder="ex: .className or #id"
                                    />
                                </PureField>
                            </>
                        )}
                    </Field>
                    <LogicalRowDivider logicalOperator={FilterLogicalOperator.And} />
                    <PureField label="User properties">
                        {(id === 'new'
                            ? survey.targeting_flag_filters?.groups || []
                            : survey.targeting_flag?.filters?.groups || []
                        ).map((group, index) => (
                            <>
                                {index > 0 && <div className="text-primary-alt font-semibold text-xs ml-2">OR</div>}
                                <div className="border rounded p-4">
                                    <div className="flex justify-between items-center">
                                        <div>
                                            Matching <b>users</b> against the criteria
                                        </div>
                                        <LemonButton
                                            icon={<IconDelete />}
                                            status="muted"
                                            size="small"
                                            noPadding
                                            onClick={() => removeConditionSet(index)}
                                        />
                                    </div>
                                    <LemonDivider className="my-3" />
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
                                                                  <IconErrorOutline className="text-xl" />{' '}
                                                                  {message.value}
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
                    </PureField>
                    <LemonButton type="secondary" className="mt-0 w-max" onClick={addConditionSet} icon={<IconPlus />}>
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
    const { survey, dataTableQuery, surveyLoading } = useValues(surveyLogic)
    // TODO: survey results logic
    // const { surveyImpressionsCount, surveyStartedCount, surveyCompletedCount } = useValues(surveyResultsLogic)
    const { editingSurvey, updateSurvey, launchSurvey, stopSurvey, archiveSurvey } = useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)
    const { cohortsById } = useValues(cohortsModel)

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')
    useEffect(() => {
        if (survey.start_date) {
            setTabKey('results')
        }
    }, [survey.start_date])

    return (
        <div>
            {surveyLoading ? (
                <LemonSkeleton />
            ) : (
                <>
                    <PageHeader
                        title={survey.name}
                        buttons={
                            <div className="flex items-center gap-2">
                                <More
                                    overlay={
                                        <>
                                            {!survey.end_date && (
                                                <>
                                                    <LemonButton
                                                        data-attr="edit-survey"
                                                        fullWidth
                                                        onClick={() => editingSurvey(true)}
                                                    >
                                                        Edit
                                                    </LemonButton>
                                                    <LemonDivider />
                                                </>
                                            )}
                                            <LemonButton status="danger" onClick={() => deleteSurvey(id)}>
                                                Delete survey
                                            </LemonButton>
                                        </>
                                    }
                                />
                                <LemonDivider vertical />
                                {!survey.start_date ? (
                                    <LemonButton type="primary" onClick={() => launchSurvey()}>
                                        Launch
                                    </LemonButton>
                                ) : survey.end_date && !survey.archived ? (
                                    <LemonButton type="secondary" onClick={() => archiveSurvey()}>
                                        Archive
                                    </LemonButton>
                                ) : (
                                    !survey.archived && (
                                        <LemonButton type="secondary" status="danger" onClick={() => stopSurvey()}>
                                            Stop
                                        </LemonButton>
                                    )
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
                                    <div className="flex flex-col w-fit">
                                        <span className="card-secondary mt-4">Type</span>
                                        <span>{capitalizeFirstLetter(SurveyType.Popover)}</span>
                                        <span className="card-secondary mt-4">Questions</span>
                                        {survey.questions.map((q, idx) => (
                                            <span key={idx}>{q.question}</span>
                                        ))}
                                        <span className="card-secondary mt-4">Linked feature flag</span>
                                        {survey.linked_flag ? (
                                            <Link to={urls.featureFlag(survey.linked_flag.id)}>
                                                {survey.linked_flag.key}
                                            </Link>
                                        ) : (
                                            <span>None</span>
                                        )}
                                        <div className="flex flex-row gap-8">
                                            {survey.start_date && (
                                                <div className="flex flex-col">
                                                    <span className="card-secondary mt-4">Start date</span>
                                                    <TZLabel time={survey.start_date} />
                                                </div>
                                            )}
                                            {survey.end_date && (
                                                <div className="flex flex-col">
                                                    <span className="card-secondary mt-4">End date</span>
                                                    <TZLabel time={survey.end_date} />
                                                </div>
                                            )}
                                        </div>
                                        {(survey.conditions || survey.targeting_flag) && (
                                            <div className="flex flex-col mt-6">
                                                <span className="font-medium text-lg">Targeting</span>
                                                {survey.conditions?.url && (
                                                    <>
                                                        <span className="card-secondary mt-4 mb-1 underline">Url</span>
                                                        <span>{survey.conditions.url}</span>
                                                        {(survey.conditions?.selector || survey.targeting_flag) && (
                                                            <LogicalRowDivider
                                                                logicalOperator={FilterLogicalOperator.And}
                                                            />
                                                        )}
                                                    </>
                                                )}
                                                {survey.conditions?.selector && (
                                                    <>
                                                        <span className="card-secondary mt-4">Selector</span>
                                                        <span>{survey.conditions.selector}</span>
                                                    </>
                                                )}
                                                {survey.targeting_flag && (
                                                    <>
                                                        <span className="card-secondary mt-4 pb-1 underline">
                                                            Release conditions
                                                        </span>
                                                        {survey.targeting_flag.filters.groups.map((group, index) => (
                                                            <>
                                                                {index > 0 && (
                                                                    <div className="text-primary-alt font-semibold text-xs ml-2 py-1">
                                                                        OR
                                                                    </div>
                                                                )}
                                                                {group.properties.map((property, idx) => (
                                                                    <>
                                                                        <div
                                                                            className="feature-flag-property-display"
                                                                            key={idx}
                                                                        >
                                                                            {idx === 0 ? (
                                                                                <LemonButton
                                                                                    icon={
                                                                                        <IconSubArrowRight className="arrow-right" />
                                                                                    }
                                                                                    status="muted"
                                                                                    size="small"
                                                                                />
                                                                            ) : (
                                                                                <LemonButton
                                                                                    icon={
                                                                                        <span className="text-sm">
                                                                                            &
                                                                                        </span>
                                                                                    }
                                                                                    status="muted"
                                                                                    size="small"
                                                                                />
                                                                            )}
                                                                            <span className="simple-tag tag-light-blue text-primary-alt">
                                                                                {property.type === 'cohort'
                                                                                    ? 'Cohort'
                                                                                    : property.key}{' '}
                                                                            </span>
                                                                            {isPropertyFilterWithOperator(property) ? (
                                                                                <span>
                                                                                    {allOperatorsToHumanName(
                                                                                        property.operator
                                                                                    )}{' '}
                                                                                </span>
                                                                            ) : null}

                                                                            {property.type === 'cohort' ? (
                                                                                <a
                                                                                    href={urls.cohort(property.value)}
                                                                                    target="_blank"
                                                                                    rel="noopener"
                                                                                    className="simple-tag tag-light-blue text-primary-alt display-value"
                                                                                >
                                                                                    {(property.value &&
                                                                                        cohortsById[property.value]
                                                                                            ?.name) ||
                                                                                        `ID ${property.value}`}
                                                                                </a>
                                                                            ) : (
                                                                                [
                                                                                    ...(Array.isArray(property.value)
                                                                                        ? property.value
                                                                                        : [property.value]),
                                                                                ].map((val, idx) => (
                                                                                    <span
                                                                                        key={idx}
                                                                                        className="simple-tag tag-light-blue text-primary-alt display-value"
                                                                                    >
                                                                                        {val}
                                                                                    </span>
                                                                                ))
                                                                            )}
                                                                        </div>
                                                                    </>
                                                                ))}
                                                            </>
                                                        ))}
                                                    </>
                                                )}
                                            </div>
                                        )}
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
                                                  {/* <div className="border rounded p-4">
                                              <span>Impressions</span>
                                              <h2>{surveyImpressionsCount}</h2>
                                          </div>
                                          <div className="border rounded p-4">
                                              <span>Started</span>
                                              <h2>{surveyStartedCount}</h2>
                                          </div>
                                          <div className="border rounded p-4">
                                              <span>Completed</span>
                                              <h2>{surveyCompletedCount}</h2>
                                          </div> */}
                                              </div>
                                              <LemonDivider />
                                              {surveyLoading ? <LemonSkeleton /> : <Query query={dataTableQuery} />}
                                          </div>
                                      ),
                                      key: 'results',
                                      label: 'Results',
                                  }
                                : null,
                        ]}
                    />
                </>
            )}
        </div>
    )
}
