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
import {
    SurveyQuestion,
    Survey,
    SurveyQuestionType,
    SurveyType,
    LinkSurveyQuestion,
    RatingSurveyQuestion,
} from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { IconCancel } from 'lib/lemon-ui/icons'
import { SurveyView } from './SurveyView'
import { SurveyAppearance } from './SurveyAppearance'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlag'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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
    const { survey, surveyLoading, isEditingSurvey, hasTargetingFlag } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey, setHasTargetingFlag } = useActions(surveyLogic)
    const { featureFlags } = useValues(featureFlagLogic)

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
                <div className="flex flex-col gap-2 min-w-180">
                    <Field name="name" label="Name">
                        <LemonInput data-attr="survey-name" />
                    </Field>
                    <Field name="description" label="Description (optional)">
                        <LemonTextArea data-attr="survey-description" />
                    </Field>
                    <Field name="type" label="Display mode" className="w-max">
                        <LemonSelect
                            data-attr="survey-type"
                            options={[
                                { label: 'Popover', value: SurveyType.Popover },
                                { label: 'API', value: SurveyType.API },
                            ]}
                        />
                    </Field>
                    <LemonDivider />
                    {survey.questions.map(
                        (question: LinkSurveyQuestion | SurveyQuestion | RatingSurveyQuestion, index: number) => (
                            <Group name={`questions.${index}`} key={index}>
                                <Field name="type" label="Question type" className="max-w-150">
                                    <LemonSelect
                                        options={[
                                            { label: 'Open text', value: SurveyQuestionType.Open },
                                            { label: 'Link', value: SurveyQuestionType.Link },
                                            ...(featureFlags[FEATURE_FLAGS.SURVEYS_RATING_TYPE]
                                                ? [{ label: 'Rating', value: SurveyQuestionType.Rating }]
                                                : []),
                                        ]}
                                    />
                                </Field>
                                <Field name="question" label="Question">
                                    <LemonInput value={question.question} />
                                </Field>
                                {question.type === SurveyQuestionType.Link && (
                                    <Field name="link" label="Link" info="Make sure to include https:// in the url.">
                                        <LemonInput value={question.link || ''} placeholder="https://posthog.com" />
                                    </Field>
                                )}
                                <Field name="description" label="Question description (optional)">
                                    <LemonTextArea value={question.description || ''} />
                                </Field>
                                {question.type === SurveyQuestionType.Rating && (
                                    <div className="flex flex-col gap-2">
                                        <div className="flex flex-row gap-4">
                                            <Field name="display" label="Display type" className="max-w-100">
                                                <LemonSelect
                                                    options={[
                                                        { label: 'Number', value: 'number' },
                                                        { label: 'Emoji', value: 'emoji' },
                                                    ]}
                                                />
                                            </Field>
                                            <Field name="scale" label="Scale" className="max-w-100">
                                                <LemonSelect
                                                    options={[
                                                        ...(question.display === 'emoji'
                                                            ? [{ label: '1 - 3', value: 3 }]
                                                            : []),
                                                        { label: '1 - 5', value: 5 },
                                                        ...(question.display === 'number'
                                                            ? [{ label: '1 - 10', value: 10 }]
                                                            : []),
                                                    ]}
                                                />
                                            </Field>
                                        </div>
                                        <div className="flex flex-row gap-4">
                                            <Field
                                                name="lowerBoundLabel"
                                                label="Lower bound label"
                                                className="max-w-150"
                                            >
                                                <LemonInput value={question.lowerBoundLabel || ''} />
                                            </Field>
                                            <Field
                                                name="upperBoundLabel"
                                                label="Upper bound label"
                                                className="max-w-150"
                                            >
                                                <LemonInput value={question.upperBoundLabel || ''} />
                                            </Field>
                                        </div>
                                    </div>
                                )}
                            </Group>
                        )
                    )}
                    <LemonDivider className="my-2" />
                    <PureField label="Targeting (optional)">
                        <span className="text-muted">
                            If targeting options are set, the survey will be released to users who match <b>all</b> of
                            the conditions. If no targeting options are set, the survey{' '}
                            <b>will be released to everyone</b>.
                        </span>
                        <Field
                            name="linked_flag_id"
                            label="Link feature flag (optional)"
                            info={
                                <>
                                    Connecting to a feature flag will automatically enable this survey for everyone in
                                    the feature flag.
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
                        <Field name="conditions">
                            {({ value, onChange }) => (
                                <>
                                    <PureField label="URL contains:">
                                        <LemonInput
                                            value={value?.url}
                                            onChange={(urlVal) => onChange({ ...value, url: urlVal })}
                                            placeholder="ex: https://app.posthog.com"
                                        />
                                    </PureField>
                                    <PureField label="Selector matches:">
                                        <LemonInput
                                            value={value?.selector}
                                            onChange={(selectorVal) => onChange({ ...value, selector: selectorVal })}
                                            placeholder="ex: .className or #id"
                                        />
                                    </PureField>
                                </>
                            )}
                        </Field>
                        <PureField label="User properties">
                            <BindLogic logic={featureFlagLogic} props={{ id: survey.targeting_flag?.id || 'new' }}>
                                {!hasTargetingFlag && (
                                    <LemonButton
                                        type="secondary"
                                        className="w-max"
                                        onClick={() => setHasTargetingFlag(true)}
                                    >
                                        Add user targeting
                                    </LemonButton>
                                )}
                                {hasTargetingFlag && (
                                    <>
                                        <div className="mt-2">
                                            <FeatureFlagReleaseConditions excludeTitle={true} />
                                        </div>
                                        {id === 'new' && (
                                            <LemonButton
                                                type="secondary"
                                                status="danger"
                                                className="w-max"
                                                onClick={() => setHasTargetingFlag(false)}
                                            >
                                                Remove all user properties
                                            </LemonButton>
                                        )}
                                    </>
                                )}
                            </BindLogic>
                        </PureField>
                    </PureField>
                </div>
                <LemonDivider vertical />
                <div className="flex flex-col flex-1 items-center min-w-80">
                    {survey.type !== SurveyType.API ? (
                        <Field name="appearance" label="">
                            {({ value, onChange }) => (
                                <SurveyAppearance
                                    type={survey.questions[0].type}
                                    surveyQuestionItem={survey.questions[0]}
                                    question={survey.questions[0].question}
                                    description={survey.questions[0].description}
                                    onAppearanceChange={(appearance) => {
                                        onChange(appearance)
                                    }}
                                    link={
                                        survey.questions[0].type === SurveyQuestionType.Link
                                            ? survey.questions[0].link
                                            : undefined
                                    }
                                    appearance={value || defaultSurveyAppearance}
                                />
                            )}
                        </Field>
                    ) : (
                        <SurveyAPIEditor survey={survey} />
                    )}
                </div>
            </div>
            <LemonDivider />
            <SurveyReleaseSummary id={id} survey={survey} hasTargetingFlag={hasTargetingFlag} />
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
    hasTargetingFlag,
}: {
    id: string
    survey: Survey | NewSurvey
    hasTargetingFlag: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col mt-2 gap-2">
            <div className="font-semibold">Release conditions</div>
            <span className="text-muted">
                By default surveys will be released to everyone unless targeting options are set.
            </span>
            {survey.conditions?.url && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>URL contains:</span>{' '}
                        <span className="simple-tag tag-light-blue text-primary-alt">{survey.conditions.url}</span>
                    </div>
                </div>
            )}
            {survey.conditions?.selector && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>Selector matches:</span>{' '}
                        <span className="simple-tag tag-light-blue text-primary-alt">{survey.conditions.selector}</span>
                    </div>
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
            <BindLogic logic={featureFlagLogic} props={{ id: survey.targeting_flag?.id || 'new' }}>
                {hasTargetingFlag && (
                    <>
                        <span className="font-medium">User properties:</span>{' '}
                        <FeatureFlagReleaseConditions readOnly excludeTitle />
                    </>
                )}
            </BindLogic>
        </div>
    )
}
