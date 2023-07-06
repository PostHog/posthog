import { SceneExport } from 'scenes/sceneTypes'
import { NewSurvey, defaultSurveyAppearance, surveyLogic } from './surveyLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Field, PureField } from 'lib/forms/Field'
import { FilterLogicalOperator, SurveyQuestion, Survey, FeatureFlagFilters, SurveyQuestionType } from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { IconCancel, IconDelete, IconErrorOutline, IconPlus, IconPlusMini, IconSubArrowRight } from 'lib/lemon-ui/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { SurveyView } from './SurveyView'
import { cohortsModel } from '~/models/cohortsModel'
import { SurveyAppearance } from './SurveyAppearance'

export const scene: SceneExport = {
    component: SurveyComponent,
    logic: surveyLogic,
    paramsToProps: ({ params: { id } }): (typeof surveyLogic)['props'] => ({
        id: id,
    }),
}

export function SurveyComponent({ id }: { id?: string } = {}): JSX.Element {
    const { isEditingSurvey } = useValues(surveyLogic)
    const showSurveyForm = id === 'new' || isEditingSurvey
    return (
        <div>
            {!id ? (
                <LemonSkeleton />
            ) : (
                <BindLogic logic={surveyLogic} props={{ id }}>
                    {showSurveyForm ? <SurveyForm id={id} /> : <SurveyView id={id} />}
                </BindLogic>
            )}
        </div>
    )
}

export function SurveyForm({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading, isEditingSurvey, propertySelectErrors, targetingFlagFilters } =
        useValues(surveyLogic)
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
                            {id === 'new' ? 'Save as draft' : 'Save'}
                        </LemonButton>
                    </div>
                }
            />
            <LemonDivider />
            <div className="flex flex-row gap-4">
                <div className="flex flex-col gap-2 max-w-160">
                    <Field name="name" label="Name">
                        <LemonInput data-attr="survey-name" />
                    </Field>
                    <Field name="description" label="Description (optional)">
                        <LemonTextArea data-attr="survey-description" />
                    </Field>
                    <Field
                        name="linked_flag_id"
                        label="Link feature flag (optional)"
                        info={
                            <>
                                Connecting to a feature flag will automatically enable this survey for everyone in the
                                feature flag.
                            </>
                        }
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
                            <Field name="type" label="Type" className="w-max">
                                <LemonSelect
                                    options={[
                                        { label: 'Open text', value: SurveyQuestionType.Open },
                                        { label: 'Link', value: SurveyQuestionType.Link },
                                    ]}
                                />
                            </Field>
                            <Field name="question" label="Question">
                                <LemonInput value={question.question} />
                            </Field>
                            <Field name="description" label="Question description (optional)">
                                <LemonTextArea value={question.description || ''} />
                            </Field>
                            {question.type === SurveyQuestionType.Link && (
                                <Field name="link" label="Link" info="Make sure to include https:// in the url.">
                                    <LemonInput value={question.link || ''} placeholder="https://posthog.com" />
                                </Field>
                            )}
                        </Group>
                    ))}
                    <PureField label="Targeting (optional)" className="mt-4">
                        <span className="text-muted">
                            Choose when the survey appears based on url, selector, and user properties.
                        </span>
                        <span>
                            <b>
                                Warning: If there are no targeting options set, the survey will display on all domains
                                to everyone.
                            </b>
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
                            {(targetingFlagFilters?.groups || []).map((group, index) => (
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
                                                        ? propertySelectErrors[index].properties.map(
                                                              (message, index) => {
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
                                                              }
                                                          )
                                                        : null
                                                }
                                            />
                                        </div>
                                    </div>
                                </>
                            ))}
                        </PureField>
                        <LemonButton
                            type="secondary"
                            className="mt-0 w-max"
                            onClick={addConditionSet}
                            icon={<IconPlus />}
                        >
                            Add condition set
                        </LemonButton>
                    </PureField>
                </div>
                <LemonDivider vertical />
                <div className="flex flex-col flex-1 items-center">
                    <Field name="appearance" label="">
                        {({ value, onChange }) => (
                            <SurveyAppearance
                                type={survey.questions[0].type}
                                question={survey.questions[0].question}
                                description={survey.questions[0].description}
                                onAppearanceChange={(appearance) => {
                                    onChange(appearance)
                                }}
                                link={survey.questions[0].link}
                                appearance={value || defaultSurveyAppearance}
                            />
                        )}
                    </Field>
                </div>
            </div>
            <LemonDivider />
            <LemonCollapse
                panels={[
                    {
                        key: '1',
                        header: 'Release summary',
                        content: (
                            <SurveyReleaseSummary id={id} survey={survey} targetingFlagFilters={targetingFlagFilters} />
                        ),
                    },
                ]}
            />
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
                    {id === 'new' ? 'Save as draft' : 'Save'}
                </LemonButton>
            </div>
        </Form>
    )
}

export function SurveyReleaseSummary({
    id,
    survey,
    targetingFlagFilters,
}: {
    id: string
    survey: Survey | NewSurvey
    targetingFlagFilters?: Pick<FeatureFlagFilters, 'groups'> | null
}): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    return (
        <div className="flex flex-col mt-2 gap-2">
            <div>
                {survey.linked_flag_id ||
                survey.conditions?.url ||
                survey.conditions?.selector ||
                targetingFlagFilters ? (
                    <>
                        This survey {survey.start_date ? 'is' : 'will be'} released to users who match <b>all</b> of the
                        following:
                    </>
                ) : (
                    <LemonTag type="highlight">
                        <span className="text-sm">
                            This survey {survey.start_date ? 'is' : 'will be'} released to everyone
                        </span>
                    </LemonTag>
                )}
            </div>
            {survey.linked_flag_id && (
                <div className="flex flex-row font-medium gap-1">
                    <span>Feature flag enabled for:</span>{' '}
                    {id !== 'new' ? (
                        survey.linked_flag?.id ? (
                            <Link to={urls.featureFlag(survey.linked_flag?.id)}>{survey.linked_flag?.key}</Link>
                        ) : null
                    ) : (
                        <FlagSelector value={survey.linked_flag_id} readOnly={true} onChange={() => {}} />
                    )}
                </div>
            )}
            {survey.conditions?.url && (
                <div className="flex flex-row font-medium gap-1">
                    <span>Url contains:</span>{' '}
                    <span className="simple-tag tag-light-blue text-primary-alt">{survey.conditions.url}</span>
                </div>
            )}
            {survey.conditions?.selector && (
                <div className="flex flex-row font-medium gap-1">
                    <span>Selector matches:</span>{' '}
                    <span className="simple-tag tag-light-blue text-primary-alt">{survey.conditions.selector}</span>
                </div>
            )}
            {(targetingFlagFilters?.groups?.[0]?.properties?.length || 0) > 0 && (
                <div className="flex flex-row font-medium gap-1">
                    <span>User conditions:</span>{' '}
                </div>
            )}
            {targetingFlagFilters?.groups?.map((group, index) => (
                <>
                    {index > 0 && <div className="text-primary-alt font-semibold text-xs ml-2 py-1">OR</div>}
                    {group.properties?.map((property, idx) => (
                        <>
                            <div className="feature-flag-property-display" key={idx}>
                                {idx === 0 ? (
                                    <LemonButton
                                        icon={<IconSubArrowRight className="arrow-right" />}
                                        status="muted"
                                        size="small"
                                    />
                                ) : (
                                    <LemonButton
                                        icon={<span className="text-sm">&</span>}
                                        status="muted"
                                        size="small"
                                    />
                                )}
                                <span className="simple-tag tag-light-blue text-primary-alt">
                                    {property.type === 'cohort' ? 'Cohort' : property.key}{' '}
                                </span>
                                {isPropertyFilterWithOperator(property) ? (
                                    <span>{allOperatorsToHumanName(property.operator)} </span>
                                ) : null}

                                {property.type === 'cohort' ? (
                                    <a
                                        href={urls.cohort(property.value)}
                                        target="_blank"
                                        rel="noopener"
                                        className="simple-tag tag-light-blue text-primary-alt display-value"
                                    >
                                        {(property.value && cohortsById[property.value]?.name) ||
                                            `ID ${property.value}`}
                                    </a>
                                ) : (
                                    [...(Array.isArray(property.value) ? property.value : [property.value])].map(
                                        (val, idx) => (
                                            <span
                                                key={idx}
                                                className="simple-tag tag-light-blue text-primary-alt display-value"
                                            >
                                                {val}
                                            </span>
                                        )
                                    )
                                )}
                            </div>
                        </>
                    ))}
                </>
            ))}
        </div>
    )
}
