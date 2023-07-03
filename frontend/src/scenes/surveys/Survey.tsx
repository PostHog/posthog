import { SceneExport } from 'scenes/sceneTypes'
import { NewSurvey, defaultSurveyAppearance, surveyLogic } from './surveyLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTextArea, Link } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Field, PureField } from 'lib/forms/Field'
import { FilterLogicalOperator, SurveyQuestion, Survey, SurveyQuestionType } from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { SurveyView } from './SurveyView'
import { SurveyAppearance } from './SurveyAppearance'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlag'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

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
    const { survey, surveyLoading, isEditingSurvey } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey } = useActions(surveyLogic)

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
                        <BindLogic logic={featureFlagLogic} props={{ id: survey.targeting_flag?.id || 'new' }}>
                            <FeatureFlagReleaseConditions />
                        </BindLogic>
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
            <PureField label="Summary">
                <SurveyReleaseSummary id={id} survey={survey} />
            </PureField>
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

export function SurveyReleaseSummary({ id, survey }: { id: string; survey: Survey | NewSurvey }): JSX.Element {
    return (
        <div className="flex flex-col mt-2 gap-2">
            <BindLogic logic={featureFlagLogic} props={{ id: survey.targeting_flag?.id || 'new' }}>
                <FeatureFlagReleaseConditions readOnly />
            </BindLogic>
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
        </div>
    )
}
