import { SceneExport } from 'scenes/sceneTypes'
import { surveyLogic } from './surveyLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTabs,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'
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
    SurveyUrlMatchType,
} from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { IconCancel, IconDelete, IconPlus, IconPlusMini } from 'lib/lemon-ui/icons'
import { SurveyView } from './SurveyView'
import { SurveyAppearance } from './SurveyAppearance'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { defaultSurveyFieldValues, defaultSurveyAppearance, NewSurvey, SurveyUrlMatchTypeLabels } from './constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { CodeEditor } from 'lib/components/CodeEditors'
import { NotFound } from 'lib/components/NotFound'

export const scene: SceneExport = {
    component: SurveyComponent,
    logic: surveyLogic,
    paramsToProps: ({ params: { id } }): (typeof surveyLogic)['props'] => ({
        id: id,
    }),
}

export function SurveyComponent({ id }: { id?: string } = {}): JSX.Element {
    const { isEditingSurvey, surveyMissing } = useValues(surveyLogic)
    const showSurveyForm = id === 'new' || isEditingSurvey

    if (surveyMissing) {
        return <NotFound object="survey" />
    }

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
    const {
        survey,
        surveyLoading,
        isEditingSurvey,
        hasTargetingFlag,
        urlMatchTypeValidationError,
        writingHTMLDescription,
    } = useValues(surveyLogic)
    const { loadSurvey, editingSurvey, setSurveyValue, setDefaultForQuestionType, setWritingHTMLDescription } =
        useActions(surveyLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)

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
                <div className="flex flex-col gap-2">
                    <Field name="name" label="Name">
                        <LemonInput data-attr="survey-name" />
                    </Field>
                    <Field name="description" label="Description (optional)">
                        <LemonTextArea data-attr="survey-description" minRows={2} />
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
                    <div className="font-semibold">Questions</div>
                    {survey.questions.map(
                        (question: LinkSurveyQuestion | SurveyQuestion | RatingSurveyQuestion, index: number) => (
                            <Group name={`questions.${index}`} key={index}>
                                <LemonCollapse
                                    defaultActiveKey="question"
                                    panels={[
                                        {
                                            key: 'question',
                                            header: (
                                                <div className="flex flex-row w-full items-center justify-between">
                                                    <b>{question.question}</b>
                                                    {survey.questions.length > 1 && (
                                                        <LemonButton
                                                            icon={<IconDelete />}
                                                            status="primary-alt"
                                                            data-attr={`delete-survey-question-${index}`}
                                                            onClick={() => {
                                                                setSurveyValue(
                                                                    'questions',
                                                                    survey.questions.filter((_, i) => i !== index)
                                                                )
                                                            }}
                                                            tooltipPlacement="topRight"
                                                        />
                                                    )}
                                                </div>
                                            ),
                                            content: (
                                                <div className="space-y-2">
                                                    <Field name="type" label="Question type" className="max-w-60">
                                                        <LemonSelect
                                                            onSelect={(newType) => {
                                                                const isEditingQuestion =
                                                                    defaultSurveyFieldValues[question.type].questions[0]
                                                                        .question !== question.question
                                                                const isEditingDescription =
                                                                    defaultSurveyFieldValues[question.type].questions[0]
                                                                        .description !== question.description
                                                                const isEditingThankYouMessage =
                                                                    defaultSurveyFieldValues[question.type].appearance
                                                                        .thankYouMessageHeader !==
                                                                    survey.appearance.thankYouMessageHeader
                                                                setDefaultForQuestionType(
                                                                    index,
                                                                    newType,
                                                                    isEditingQuestion,
                                                                    isEditingDescription,
                                                                    isEditingThankYouMessage
                                                                )
                                                            }}
                                                            options={[
                                                                { label: 'Open text', value: SurveyQuestionType.Open },
                                                                { label: 'Link', value: SurveyQuestionType.Link },
                                                                { label: 'Rating', value: SurveyQuestionType.Rating },
                                                                ...[
                                                                    {
                                                                        label: 'Single choice select',
                                                                        value: SurveyQuestionType.SingleChoice,
                                                                    },
                                                                    {
                                                                        label: 'Multiple choice select',
                                                                        value: SurveyQuestionType.MultipleChoice,
                                                                    },
                                                                ],
                                                            ]}
                                                        />
                                                    </Field>
                                                    {survey.questions.length > 1 && (
                                                        <Field name="optional" className="my-2">
                                                            <LemonCheckbox
                                                                label="Optional"
                                                                checked={!!question.optional}
                                                            />
                                                        </Field>
                                                    )}
                                                    <Field name="question" label="Question">
                                                        <LemonInput value={question.question} />
                                                    </Field>
                                                    {question.type === SurveyQuestionType.Link && (
                                                        <Field
                                                            name="link"
                                                            label="Link"
                                                            info="Make sure to include https:// in the url."
                                                        >
                                                            <LemonInput
                                                                value={question.link || ''}
                                                                placeholder="https://posthog.com"
                                                            />
                                                        </Field>
                                                    )}
                                                    <Field name="description" label="Question description (optional)">
                                                        {({ value, onChange }) => (
                                                            <>
                                                                <LemonTabs
                                                                    activeKey={writingHTMLDescription ? 'html' : 'text'}
                                                                    onChange={(key) =>
                                                                        setWritingHTMLDescription(key === 'html')
                                                                    }
                                                                    tabs={[
                                                                        {
                                                                            key: 'text',
                                                                            label: (
                                                                                <span className="text-sm">Text</span>
                                                                            ),
                                                                            content: (
                                                                                <LemonTextArea
                                                                                    data-attr="survey-description"
                                                                                    minRows={2}
                                                                                    value={value}
                                                                                    onChange={(v) => onChange(v)}
                                                                                />
                                                                            ),
                                                                        },
                                                                        {
                                                                            key: 'html',
                                                                            label: (
                                                                                <span className="text-sm">HTML</span>
                                                                            ),
                                                                            content: (
                                                                                <div>
                                                                                    <CodeEditor
                                                                                        className="border"
                                                                                        language="html"
                                                                                        value={value}
                                                                                        onChange={(v) =>
                                                                                            onChange(v ?? '')
                                                                                        }
                                                                                        height={150}
                                                                                        options={{
                                                                                            minimap: { enabled: false },
                                                                                            wordWrap: 'on',
                                                                                            scrollBeyondLastLine: false,
                                                                                            automaticLayout: true,
                                                                                            fixedOverflowWidgets: true,
                                                                                            lineNumbers: 'off',
                                                                                            glyphMargin: false,
                                                                                            folding: false,
                                                                                        }}
                                                                                    />
                                                                                </div>
                                                                            ),
                                                                        },
                                                                    ]}
                                                                />
                                                                {question.description &&
                                                                    question.description
                                                                        ?.toLowerCase()
                                                                        .includes('<script') && (
                                                                        <LemonBanner type="warning">
                                                                            Scripts won't run in the survey popup and
                                                                            we'll remove these on save. Use the API
                                                                            question mode to run your own scripts in
                                                                            surveys.
                                                                        </LemonBanner>
                                                                    )}
                                                            </>
                                                        )}
                                                    </Field>
                                                    {question.type === SurveyQuestionType.Rating && (
                                                        <div className="flex flex-col gap-2">
                                                            <div className="flex flex-row gap-4">
                                                                <Field
                                                                    name="display"
                                                                    label="Display type"
                                                                    className="min-w-50"
                                                                >
                                                                    <LemonSelect
                                                                        options={[
                                                                            { label: 'Number', value: 'number' },
                                                                            { label: 'Emoji', value: 'emoji' },
                                                                        ]}
                                                                    />
                                                                </Field>
                                                                <Field name="scale" label="Scale" className="min-w-50">
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
                                                                    className="min-w-150"
                                                                >
                                                                    <LemonInput
                                                                        value={question.lowerBoundLabel || ''}
                                                                    />
                                                                </Field>
                                                                <Field
                                                                    name="upperBoundLabel"
                                                                    label="Upper bound label"
                                                                    className="min-w-150"
                                                                >
                                                                    <LemonInput
                                                                        value={question.upperBoundLabel || ''}
                                                                    />
                                                                </Field>
                                                            </div>
                                                        </div>
                                                    )}
                                                    {(question.type === SurveyQuestionType.SingleChoice ||
                                                        question.type === SurveyQuestionType.MultipleChoice) && (
                                                        <div className="flex flex-col gap-2">
                                                            <Field name="choices" label="Choices">
                                                                {({ value, onChange }) => (
                                                                    <div className="flex flex-col gap-2">
                                                                        {(value || []).map(
                                                                            (choice: string, index: number) => (
                                                                                <div
                                                                                    className="flex flex-row gap-2"
                                                                                    key={index}
                                                                                >
                                                                                    <LemonInput
                                                                                        value={choice}
                                                                                        fullWidth
                                                                                        onChange={(val) => {
                                                                                            const newChoices = [
                                                                                                ...value,
                                                                                            ]
                                                                                            newChoices[index] = val
                                                                                            onChange(newChoices)
                                                                                        }}
                                                                                    />
                                                                                    <LemonButton
                                                                                        icon={<IconDelete />}
                                                                                        size="small"
                                                                                        status="muted"
                                                                                        noPadding
                                                                                        onClick={() => {
                                                                                            const newChoices = [
                                                                                                ...value,
                                                                                            ]
                                                                                            newChoices.splice(index, 1)
                                                                                            onChange(newChoices)
                                                                                        }}
                                                                                    />
                                                                                </div>
                                                                            )
                                                                        )}
                                                                        <div className="w-fit">
                                                                            {(value || []).length < 6 && (
                                                                                <LemonButton
                                                                                    icon={<IconPlusMini />}
                                                                                    type="secondary"
                                                                                    fullWidth={false}
                                                                                    onClick={() => {
                                                                                        if (!value) {
                                                                                            onChange([''])
                                                                                        } else {
                                                                                            onChange([...value, ''])
                                                                                        }
                                                                                    }}
                                                                                >
                                                                                    Add choice
                                                                                </LemonButton>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                )}
                                                            </Field>
                                                        </div>
                                                    )}
                                                </div>
                                            ),
                                        },
                                    ]}
                                />
                            </Group>
                        )
                    )}
                    {featureFlags[FEATURE_FLAGS.SURVEYS_MULTIPLE_QUESTIONS] && (
                        // TODO: Add pay gate mini here once billing is resolved for it
                        <LemonButton
                            type="secondary"
                            className="w-max"
                            icon={<IconPlus />}
                            onClick={() => {
                                setSurveyValue('questions', [
                                    ...survey.questions,
                                    { ...defaultSurveyFieldValues.open.questions[0] },
                                ])
                            }}
                        >
                            Add question
                        </LemonButton>
                    )}
                    <LemonDivider />
                    <Field name="appearance" label="Thank you message (optional)">
                        {({ value, onChange }) => (
                            <>
                                <LemonCheckbox
                                    label="Display thank you message"
                                    checked={value.displayThankYouMessage}
                                    onChange={(checked) => onChange({ ...value, displayThankYouMessage: checked })}
                                />
                                {value.displayThankYouMessage && (
                                    <>
                                        <PureField label="Thank you header">
                                            <LemonInput
                                                value={value.thankYouMessageHeader}
                                                onChange={(val) => onChange({ ...value, thankYouMessageHeader: val })}
                                                placeholder="ex: Thank you for your feedback!"
                                            />
                                        </PureField>
                                        <PureField label="Thank you description">
                                            <LemonTextArea
                                                value={value.thankYouMessageDescription}
                                                onChange={(val) =>
                                                    onChange({ ...value, thankYouMessageDescription: val })
                                                }
                                                minRows={2}
                                                placeholder="ex: We really appreciate it."
                                            />
                                        </PureField>
                                    </>
                                )}
                            </>
                        )}
                    </Field>
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
                                    <PureField
                                        label="URL targeting"
                                        error={urlMatchTypeValidationError}
                                        info="Targeting by regex or exact match requires atleast version 1.82 of posthog-js"
                                    >
                                        <div className="flex flex-row gap-2 items-center">
                                            URL
                                            <LemonSelect
                                                value={value?.urlMatchType || SurveyUrlMatchType.Contains}
                                                onChange={(matchTypeVal) => {
                                                    onChange({ ...value, urlMatchType: matchTypeVal })
                                                }}
                                                data-attr="survey-url-matching-type"
                                                options={Object.keys(SurveyUrlMatchTypeLabels).map((key) => ({
                                                    label: SurveyUrlMatchTypeLabels[key],
                                                    value: key,
                                                }))}
                                            />
                                            <LemonInput
                                                value={value?.url}
                                                onChange={(urlVal) => onChange({ ...value, url: urlVal })}
                                                placeholder="ex: https://app.posthog.com"
                                                fullWidth
                                            />
                                        </div>
                                    </PureField>
                                    <PureField label="Selector matches:">
                                        <LemonInput
                                            value={value?.selector}
                                            onChange={(selectorVal) => onChange({ ...value, selector: selectorVal })}
                                            placeholder="ex: .className or #id"
                                        />
                                    </PureField>
                                    <PureField label="Survey wait period">
                                        <div className="flex flex-row gap-2 items-center">
                                            <LemonCheckbox
                                                checked={!!value?.seenSurveyWaitPeriodInDays}
                                                onChange={(checked) => {
                                                    if (checked) {
                                                        onChange({
                                                            ...value,
                                                            seenSurveyWaitPeriodInDays:
                                                                value?.seenSurveyWaitPeriodInDays || 30,
                                                        })
                                                    } else {
                                                        const { seenSurveyWaitPeriodInDays, ...rest } = value || {}
                                                        onChange(rest)
                                                    }
                                                }}
                                            />
                                            Do not display this survey to users who have already seen a survey in the
                                            last
                                            <LemonInput
                                                type="number"
                                                size="small"
                                                min={0}
                                                value={value?.seenSurveyWaitPeriodInDays}
                                                onChange={(val) => {
                                                    if (val !== undefined && val > 0) {
                                                        onChange({ ...value, seenSurveyWaitPeriodInDays: val })
                                                    }
                                                }}
                                                className="w-16"
                                            />{' '}
                                            days.
                                        </div>
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
                                        onClick={() => {
                                            setSurveyValue('targeting_flag_filters', { groups: [] })
                                            setSurveyValue('remove_targeting_flag', false)
                                        }}
                                    >
                                        Add user targeting
                                    </LemonButton>
                                )}
                                {hasTargetingFlag && (
                                    <>
                                        <div className="mt-2">
                                            <FeatureFlagReleaseConditions excludeTitle={true} />
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            status="danger"
                                            className="w-max"
                                            onClick={() => {
                                                setSurveyValue('targeting_flag_filters', null)
                                                setSurveyValue('targeting_flag', null)
                                                setSurveyValue('remove_targeting_flag', true)
                                            }}
                                        >
                                            Remove all user properties
                                        </LemonButton>
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
                <LemonButton type="primary" data-attr="save-survey" htmlType="submit" loading={surveyLoading}>
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
            <div className="font-semibold">Release conditions summary</div>
            <span className="text-muted">
                By default surveys will be released to everyone unless targeting options are set.
            </span>
            {survey.conditions?.url && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex-row">
                        <span>
                            URL{' '}
                            {SurveyUrlMatchTypeLabels[
                                survey.conditions?.urlMatchType || SurveyUrlMatchType.Contains
                            ].slice(2)}
                            :
                        </span>{' '}
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
