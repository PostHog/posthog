import { surveyLogic } from './surveyLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { Group } from 'kea-forms'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'
import { Field, PureField } from 'lib/forms/Field'
import {
    SurveyQuestion,
    SurveyQuestionType,
    SurveyType,
    LinkSurveyQuestion,
    RatingSurveyQuestion,
    SurveyAppearance as SurveyAppearanceType,
} from '~/types'
import { FlagSelector } from 'scenes/early-access-features/EarlyAccessFeature'
import { IconCancel, IconDelete, IconPlus, IconPlusMini } from 'lib/lemon-ui/icons'
import {
    BaseAppearance,
    SurveyAppearance,
    SurveyMultipleChoiceAppearance,
    SurveyRatingAppearance,
} from './SurveyAppearance'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { defaultSurveyFieldValues, defaultSurveyAppearance } from './constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import React from 'react'

function FormTypeCard({
    title,
    description,
    children,
    type,
    onClick,
    value,
    active,
}: {
    title: string
    description?: string
    children: React.ReactNode
    type: SurveyQuestionType
    onClick: (type: SurveyQuestionType) => void
    value: SurveyQuestionType
    active: boolean
}): JSX.Element {
    return (
        <div
            style={{ borderColor: active ? 'var(--primary)' : 'var(--border)' }}
            className="border rounded-md relative px-4 py-2"
        >
            <p className="font-semibold m-0">{title}</p>
            {description && <p className="m-0 text-xs">{description}</p>}
            <div className="survey-preview relative mt-2">{children}</div>
            <input
                onClick={() => onClick(type)}
                className="opacity-0 absolute inset-0 h-full w-full cursor-pointer"
                name="type"
                value={value}
                type="radio"
            />
        </div>
    )
}

export function FormType({
    onChange,
    appearance,
    value,
}: {
    onChange: (type: SurveyQuestionType) => void
    appearance: SurveyAppearanceType
    value: string
}): JSX.Element {
    return (
        <div className="flex flex-wrap list-none text-center mb-2 gap-4">
            <FormTypeCard
                type={SurveyQuestionType.Open}
                onClick={onChange}
                title="Freeform text"
                value={SurveyQuestionType.Open}
                active={value === SurveyQuestionType.Open}
            >
                <BaseAppearance
                    preview
                    onSubmit={() => undefined}
                    appearance={{ ...appearance, whiteLabel: true }}
                    question="Share your thoughts"
                    description="Optional form description."
                    type={SurveyQuestionType.Open}
                />
            </FormTypeCard>
            <FormTypeCard
                type={SurveyQuestionType.Rating}
                onClick={onChange}
                title="Rating"
                description="Numerical or emoji"
                value={SurveyQuestionType.Rating}
                active={value === SurveyQuestionType.Rating}
            >
                <div style={{ transform: 'scale(.8)', top: '1rem' }} className="absolute">
                    <SurveyRatingAppearance
                        preview
                        onSubmit={() => undefined}
                        appearance={{ ...appearance, whiteLabel: true, ratingButtonColor: 'black' }}
                        question="How do you feel about this page?"
                        description="Optional form description."
                        ratingSurveyQuestion={{
                            display: 'emoji',
                            lowerBoundLabel: 'Not great',
                            upperBoundLabel: 'Fantastic',
                            question: 'How do you feel about this page?',
                            scale: 3,
                            type: SurveyQuestionType.Rating,
                        }}
                    />
                </div>
                <div style={{ transform: 'scale(.8)', marginLeft: '-1.5rem' }}>
                    <SurveyRatingAppearance
                        preview
                        onSubmit={() => undefined}
                        appearance={{ ...appearance, whiteLabel: true }}
                        question="How satisfied are you with our product?"
                        description="Optional form description."
                        ratingSurveyQuestion={{
                            display: 'number',
                            lowerBoundLabel: 'Not great',
                            upperBoundLabel: 'Fantastic',
                            question: 'How satisfied are you with our product?',
                            scale: 5,
                            type: SurveyQuestionType.Rating,
                        }}
                    />
                </div>
            </FormTypeCard>
            <FormTypeCard
                type={SurveyQuestionType.MultipleChoice}
                onClick={onChange}
                title="Multiple choice"
                value={SurveyQuestionType.MultipleChoice}
                active={value === SurveyQuestionType.MultipleChoice}
            >
                <SurveyMultipleChoiceAppearance
                    initialChecked={[0, 1]}
                    preview
                    onSubmit={() => undefined}
                    appearance={{ ...appearance, whiteLabel: true }}
                    question="Which types of content would you like to see more of?"
                    multipleChoiceQuestion={{
                        type: SurveyQuestionType.MultipleChoice,
                        choices: ['Tutorials', 'Customer case studies', 'Product announcements'],
                        question: 'Which types of content would you like to see more of?',
                    }}
                />
            </FormTypeCard>
            <FormTypeCard
                type={SurveyQuestionType.SingleChoice}
                onClick={onChange}
                title="Single choice"
                value={SurveyQuestionType.SingleChoice}
                active={value === SurveyQuestionType.SingleChoice}
            >
                <SurveyMultipleChoiceAppearance
                    initialChecked={[0]}
                    preview
                    onSubmit={() => undefined}
                    appearance={{ ...appearance, whiteLabel: true }}
                    question="Have you found this tutorial useful?"
                    multipleChoiceQuestion={{
                        type: SurveyQuestionType.SingleChoice,
                        choices: ['Yes', 'No'],
                        question: 'Have you found this tutorial useful?',
                    }}
                />
            </FormTypeCard>
            <FormTypeCard
                type={SurveyQuestionType.Link}
                onClick={onChange}
                title="Link"
                value={SurveyQuestionType.Link}
                active={value === SurveyQuestionType.Link}
            >
                <BaseAppearance
                    preview
                    onSubmit={() => undefined}
                    appearance={{ ...appearance, whiteLabel: true, submitButtonText: 'Register' }}
                    question="Do you want to join our upcoming webinar?"
                    type={SurveyQuestionType.Link}
                />
            </FormTypeCard>
        </div>
    )
}

export default function EditSurveyNew(): JSX.Element {
    const { survey, hasTargetingFlag } = useValues(surveyLogic)
    const { setSurveyValue, setDefaultForQuestionType } = useActions(surveyLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)

    return (
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
                                            <>
                                                <Field name="type" label="Question type">
                                                    {({ value, onChange }) => {
                                                        return (
                                                            <FormType
                                                                value={value}
                                                                appearance={survey.appearance}
                                                                onChange={(newType) => {
                                                                    onChange(newType)
                                                                    const isEditingQuestion =
                                                                        defaultSurveyFieldValues[question.type]
                                                                            .questions[0].question !== question.question
                                                                    const isEditingDescription =
                                                                        defaultSurveyFieldValues[question.type]
                                                                            .questions[0].description !==
                                                                        question.description
                                                                    const isEditingThankYouMessage =
                                                                        defaultSurveyFieldValues[question.type]
                                                                            .appearance.thankYouMessageHeader !==
                                                                        survey.appearance.thankYouMessageHeader
                                                                    setDefaultForQuestionType(
                                                                        index,
                                                                        newType,
                                                                        isEditingQuestion,
                                                                        isEditingDescription,
                                                                        isEditingThankYouMessage
                                                                    )
                                                                }}
                                                            />
                                                        )
                                                    }}
                                                </Field>
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
                                                    <LemonTextArea value={question.description || ''} minRows={2} />
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
                                                                <LemonInput value={question.lowerBoundLabel || ''} />
                                                            </Field>
                                                            <Field
                                                                name="upperBoundLabel"
                                                                label="Upper bound label"
                                                                className="min-w-150"
                                                            >
                                                                <LemonInput value={question.upperBoundLabel || ''} />
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
                                                                                        const newChoices = [...value]
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
                                                                                        const newChoices = [...value]
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
                                            </>
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
                            setSurveyValue('questions', [...survey.questions, { ...defaultSurveyFieldValues.open }])
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
                                            onChange={(val) => onChange({ ...value, thankYouMessageDescription: val })}
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
                        If targeting options are set, the survey will be released to users who match <b>all</b> of the
                        conditions. If no targeting options are set, the survey <b>will be released to everyone</b>.
                    </span>
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
                                        Do not display this survey to users who have already seen a survey in the last
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
    )
}
