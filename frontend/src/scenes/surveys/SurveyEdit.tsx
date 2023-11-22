import './EditSurvey.scss'
import { SurveyEditSection, surveyLogic } from './surveyLogic'
import { BindLogic, useActions, useValues } from 'kea'
import { Group } from 'kea-forms'
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
import { Field, PureField } from 'lib/forms/Field'
import {
    SurveyQuestion,
    SurveyQuestionType,
    SurveyType,
    LinkSurveyQuestion,
    RatingSurveyQuestion,
    SurveyUrlMatchType,
    AvailableFeature,
} from '~/types'
import { IconCancel, IconDelete, IconLock, IconPlus, IconPlusMini } from 'lib/lemon-ui/icons'
import {
    BaseAppearance,
    Customization,
    SurveyAppearance,
    SurveyMultipleChoiceAppearance,
    SurveyRatingAppearance,
} from './SurveyAppearance'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import {
    defaultSurveyFieldValues,
    defaultSurveyAppearance,
    SurveyQuestionLabel,
    SurveyUrlMatchTypeLabels,
} from './constants'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import React from 'react'
import { CodeEditor } from 'lib/components/CodeEditors'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { surveysLogic } from './surveysLogic'
import { FlagSelector } from 'lib/components/FlagSelector'
import clsx from 'clsx'

function PresentationTypeCard({
    title,
    description,
    children,
    onClick,
    value,
    active,
}: {
    title: string
    description?: string
    children: React.ReactNode
    onClick: () => void
    value: any
    active: boolean
}): JSX.Element {
    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: 230, width: 260 }}
            className={clsx(
                'border rounded-md relative px-4 py-2 overflow-hidden',
                active ? 'border-primary' : 'border-border'
            )}
        >
            <p className="font-semibold m-0">{title}</p>
            {description && <p className="m-0 text-xs">{description}</p>}
            <div className="relative mt-2 presentation-preview">{children}</div>
            <input
                onClick={onClick}
                className="opacity-0 absolute inset-0 h-full w-full cursor-pointer"
                name="type"
                value={value}
                type="radio"
            />
        </div>
    )
}

export default function SurveyEdit(): JSX.Element {
    const {
        survey,
        hasTargetingFlag,
        urlMatchTypeValidationError,
        writingHTMLDescription,
        hasTargetingSet,
        selectedQuestion,
        selectedSection,
    } = useValues(surveyLogic)
    const {
        setSurveyValue,
        setDefaultForQuestionType,
        setWritingHTMLDescription,
        resetTargeting,
        setSelectedQuestion,
        setSelectedSection,
    } = useActions(surveyLogic)
    const { surveysMultipleQuestionsAvailable } = useValues(surveysLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)

    return (
        <div className="flex flex-row gap-4">
            <div className="flex flex-col gap-2 flex-1 SurveyForm">
                <Field name="name" label="Name">
                    <LemonInput data-attr="survey-name" />
                </Field>
                <Field name="description" label="Description (optional)">
                    <LemonTextArea data-attr="survey-description" minRows={2} />
                </Field>
                <LemonCollapse
                    activeKey={selectedSection || undefined}
                    onChange={(section) => {
                        setSelectedSection(section)
                    }}
                    panels={[
                        {
                            key: SurveyEditSection.Steps,
                            header: 'Steps',
                            content: (
                                <>
                                    <LemonCollapse
                                        activeKey={selectedQuestion === null ? undefined : selectedQuestion}
                                        onChange={(index) => {
                                            setSelectedQuestion(index)
                                        }}
                                        panels={[
                                            ...survey.questions.map(
                                                (
                                                    question:
                                                        | LinkSurveyQuestion
                                                        | SurveyQuestion
                                                        | RatingSurveyQuestion,
                                                    index: number
                                                ) => ({
                                                    key: index,
                                                    header: (
                                                        <div className="flex flex-row w-full items-center justify-between">
                                                            <b>
                                                                Question {index + 1}. {question.question}
                                                            </b>
                                                            {survey.questions.length > 1 && (
                                                                <LemonButton
                                                                    icon={<IconDelete />}
                                                                    status="primary-alt"
                                                                    data-attr={`delete-survey-question-${index}`}
                                                                    onClick={(e) => {
                                                                        e.stopPropagation()
                                                                        setSelectedQuestion(index <= 0 ? 0 : index - 1)
                                                                        setSurveyValue(
                                                                            'questions',
                                                                            survey.questions.filter(
                                                                                (_, i) => i !== index
                                                                            )
                                                                        )
                                                                    }}
                                                                    tooltipPlacement="topRight"
                                                                />
                                                            )}
                                                        </div>
                                                    ),
                                                    content: (
                                                        <Group name={`questions.${index}`} key={index}>
                                                            <div className="flex flex-col gap-2">
                                                                <Field
                                                                    name="type"
                                                                    label="Question type"
                                                                    className="max-w-60"
                                                                >
                                                                    <LemonSelect
                                                                        data-attr={`survey-question-type-${index}`}
                                                                        onSelect={(newType) => {
                                                                            const isEditingQuestion =
                                                                                defaultSurveyFieldValues[question.type]
                                                                                    .questions[0].question !==
                                                                                question.question
                                                                            const isEditingDescription =
                                                                                defaultSurveyFieldValues[question.type]
                                                                                    .questions[0].description !==
                                                                                question.description
                                                                            const isEditingThankYouMessage =
                                                                                defaultSurveyFieldValues[question.type]
                                                                                    .appearance
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
                                                                            {
                                                                                label: SurveyQuestionLabel[
                                                                                    SurveyQuestionType.Open
                                                                                ],
                                                                                value: SurveyQuestionType.Open,
                                                                                tooltip: () => (
                                                                                    <BaseAppearance
                                                                                        preview
                                                                                        onSubmit={() => undefined}
                                                                                        appearance={{
                                                                                            ...survey.appearance,
                                                                                            whiteLabel: true,
                                                                                        }}
                                                                                        question={{
                                                                                            type: SurveyQuestionType.Open,
                                                                                            question:
                                                                                                'Share your thoughts',
                                                                                            description:
                                                                                                'Optional form description',
                                                                                        }}
                                                                                    />
                                                                                ),
                                                                            },
                                                                            {
                                                                                label: 'Link',
                                                                                value: SurveyQuestionType.Link,
                                                                                tooltip: () => (
                                                                                    <BaseAppearance
                                                                                        preview
                                                                                        onSubmit={() => undefined}
                                                                                        appearance={{
                                                                                            ...survey.appearance,
                                                                                            whiteLabel: true,
                                                                                        }}
                                                                                        question={{
                                                                                            type: SurveyQuestionType.Link,
                                                                                            question:
                                                                                                'Do you want to join our upcoming webinar?',
                                                                                            buttonText: 'Register',
                                                                                            link: '',
                                                                                        }}
                                                                                    />
                                                                                ),
                                                                            },
                                                                            {
                                                                                label: 'Rating',
                                                                                value: SurveyQuestionType.Rating,
                                                                                tooltip: () => (
                                                                                    <SurveyRatingAppearance
                                                                                        preview
                                                                                        onSubmit={() => undefined}
                                                                                        appearance={{
                                                                                            ...survey.appearance,
                                                                                            whiteLabel: true,
                                                                                        }}
                                                                                        ratingSurveyQuestion={{
                                                                                            question:
                                                                                                'How satisfied are you with our product?',
                                                                                            description:
                                                                                                'Optional form description.',
                                                                                            display: 'number',
                                                                                            lowerBoundLabel:
                                                                                                'Not great',
                                                                                            upperBoundLabel:
                                                                                                'Fantastic',
                                                                                            scale: 5,
                                                                                            type: SurveyQuestionType.Rating,
                                                                                        }}
                                                                                    />
                                                                                ),
                                                                            },
                                                                            ...[
                                                                                {
                                                                                    label: 'Single choice select',
                                                                                    value: SurveyQuestionType.SingleChoice,
                                                                                    tooltip: () => (
                                                                                        <SurveyMultipleChoiceAppearance
                                                                                            initialChecked={[0]}
                                                                                            preview
                                                                                            onSubmit={() => undefined}
                                                                                            appearance={{
                                                                                                ...survey.appearance,
                                                                                                whiteLabel: true,
                                                                                            }}
                                                                                            multipleChoiceQuestion={{
                                                                                                type: SurveyQuestionType.SingleChoice,
                                                                                                choices: ['Yes', 'No'],
                                                                                                question:
                                                                                                    'Have you found this tutorial useful?',
                                                                                            }}
                                                                                        />
                                                                                    ),
                                                                                },
                                                                                {
                                                                                    label: 'Multiple choice select',
                                                                                    value: SurveyQuestionType.MultipleChoice,
                                                                                    tooltip: () => (
                                                                                        <SurveyMultipleChoiceAppearance
                                                                                            initialChecked={[0, 1]}
                                                                                            preview
                                                                                            onSubmit={() => undefined}
                                                                                            appearance={{
                                                                                                ...survey.appearance,
                                                                                                whiteLabel: true,
                                                                                            }}
                                                                                            multipleChoiceQuestion={{
                                                                                                type: SurveyQuestionType.MultipleChoice,
                                                                                                choices: [
                                                                                                    'Tutorials',
                                                                                                    'Customer case studies',
                                                                                                    'Product announcements',
                                                                                                ],
                                                                                                question:
                                                                                                    'Which types of content would you like to see more of?',
                                                                                            }}
                                                                                        />
                                                                                    ),
                                                                                },
                                                                            ],
                                                                        ]}
                                                                    />
                                                                </Field>
                                                                <Field name="question" label="Label">
                                                                    <LemonInput value={question.question} />
                                                                </Field>

                                                                <Field
                                                                    name="description"
                                                                    label="Description (optional)"
                                                                >
                                                                    {({ value, onChange }) => (
                                                                        <HTMLEditor
                                                                            value={value}
                                                                            onChange={onChange}
                                                                            writingHTMLDescription={
                                                                                writingHTMLDescription
                                                                            }
                                                                            setWritingHTMLDescription={
                                                                                setWritingHTMLDescription
                                                                            }
                                                                        />
                                                                    )}
                                                                </Field>
                                                                {survey.questions.length > 1 && (
                                                                    <Field name="optional" className="my-2">
                                                                        <LemonCheckbox
                                                                            label="Optional"
                                                                            checked={!!question.optional}
                                                                        />
                                                                    </Field>
                                                                )}
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
                                                                {question.type === SurveyQuestionType.Rating && (
                                                                    <div className="flex flex-col gap-2">
                                                                        <div className="flex flex-row gap-4">
                                                                            <Field
                                                                                name="display"
                                                                                label="Display type"
                                                                                className="w-1/2"
                                                                            >
                                                                                <LemonSelect
                                                                                    options={[
                                                                                        {
                                                                                            label: 'Number',
                                                                                            value: 'number',
                                                                                        },
                                                                                        {
                                                                                            label: 'Emoji',
                                                                                            value: 'emoji',
                                                                                        },
                                                                                    ]}
                                                                                />
                                                                            </Field>
                                                                            <Field
                                                                                name="scale"
                                                                                label="Scale"
                                                                                className="w-1/2"
                                                                            >
                                                                                <LemonSelect
                                                                                    options={[
                                                                                        ...(question.display === 'emoji'
                                                                                            ? [
                                                                                                  {
                                                                                                      label: '1 - 3',
                                                                                                      value: 3,
                                                                                                  },
                                                                                              ]
                                                                                            : []),
                                                                                        {
                                                                                            label: '1 - 5',
                                                                                            value: 5,
                                                                                        },
                                                                                        ...(question.display ===
                                                                                        'number'
                                                                                            ? [
                                                                                                  {
                                                                                                      label: '0 - 10',
                                                                                                      value: 10,
                                                                                                  },
                                                                                              ]
                                                                                            : []),
                                                                                    ]}
                                                                                />
                                                                            </Field>
                                                                        </div>
                                                                        <div className="flex flex-row gap-4">
                                                                            <Field
                                                                                name="lowerBoundLabel"
                                                                                label="Lower bound label"
                                                                                className="w-1/2"
                                                                            >
                                                                                <LemonInput
                                                                                    value={
                                                                                        question.lowerBoundLabel || ''
                                                                                    }
                                                                                />
                                                                            </Field>
                                                                            <Field
                                                                                name="upperBoundLabel"
                                                                                label="Upper bound label"
                                                                                className="w-1/2"
                                                                            >
                                                                                <LemonInput
                                                                                    value={
                                                                                        question.upperBoundLabel || ''
                                                                                    }
                                                                                />
                                                                            </Field>
                                                                        </div>
                                                                    </div>
                                                                )}
                                                                {(question.type === SurveyQuestionType.SingleChoice ||
                                                                    question.type ===
                                                                        SurveyQuestionType.MultipleChoice) && (
                                                                    <div className="flex flex-col gap-2">
                                                                        <Field name="choices" label="Choices">
                                                                            {({
                                                                                value,
                                                                                onChange,
                                                                            }: {
                                                                                value: string[]
                                                                                onChange: (newValue: string[]) => void
                                                                            }) => (
                                                                                <div className="flex flex-col gap-2">
                                                                                    {(value || []).map(
                                                                                        (
                                                                                            choice: string,
                                                                                            index: number
                                                                                        ) => (
                                                                                            <div
                                                                                                className="flex flex-row gap-2"
                                                                                                key={index}
                                                                                            >
                                                                                                <LemonInput
                                                                                                    value={choice}
                                                                                                    fullWidth
                                                                                                    onChange={(val) => {
                                                                                                        const newChoices =
                                                                                                            [...value]
                                                                                                        newChoices[
                                                                                                            index
                                                                                                        ] = val
                                                                                                        onChange(
                                                                                                            newChoices
                                                                                                        )
                                                                                                    }}
                                                                                                />
                                                                                                <LemonButton
                                                                                                    icon={
                                                                                                        <IconDelete />
                                                                                                    }
                                                                                                    size="small"
                                                                                                    status="muted"
                                                                                                    noPadding
                                                                                                    onClick={() => {
                                                                                                        const newChoices =
                                                                                                            [...value]
                                                                                                        newChoices.splice(
                                                                                                            index,
                                                                                                            1
                                                                                                        )
                                                                                                        onChange(
                                                                                                            newChoices
                                                                                                        )
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
                                                                                                        onChange([
                                                                                                            ...value,
                                                                                                            '',
                                                                                                        ])
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
                                                                <Field name="buttonText" label="Button text">
                                                                    <LemonInput
                                                                        value={
                                                                            question.buttonText === undefined
                                                                                ? survey.questions.length > 1 &&
                                                                                  index !== survey.questions.length - 1
                                                                                    ? 'Next'
                                                                                    : survey.appearance.submitButtonText
                                                                                : question.buttonText
                                                                        }
                                                                    />
                                                                </Field>
                                                            </div>
                                                        </Group>
                                                    ),
                                                })
                                            ),
                                            ...(survey.appearance.displayThankYouMessage
                                                ? [
                                                      {
                                                          key: survey.questions.length,
                                                          header: (
                                                              <div className="flex flex-row w-full items-center justify-between">
                                                                  <b>Confirmation message</b>
                                                                  <LemonButton
                                                                      icon={<IconDelete />}
                                                                      status="primary-alt"
                                                                      data-attr={`delete-survey-confirmation`}
                                                                      onClick={(e) => {
                                                                          e.stopPropagation()
                                                                          setSelectedQuestion(
                                                                              survey.questions.length - 1
                                                                          )
                                                                          setSurveyValue('appearance', {
                                                                              ...survey.appearance,
                                                                              displayThankYouMessage: false,
                                                                          })
                                                                      }}
                                                                      tooltipPlacement="topRight"
                                                                  />
                                                              </div>
                                                          ),
                                                          content: (
                                                              <>
                                                                  <PureField label="Thank you header">
                                                                      <LemonInput
                                                                          value={
                                                                              survey.appearance.thankYouMessageHeader
                                                                          }
                                                                          onChange={(val) =>
                                                                              setSurveyValue('appearance', {
                                                                                  ...survey.appearance,
                                                                                  thankYouMessageHeader: val,
                                                                              })
                                                                          }
                                                                          placeholder="ex: Thank you for your feedback!"
                                                                      />
                                                                  </PureField>
                                                                  <PureField
                                                                      label="Thank you description"
                                                                      className="mt-1"
                                                                  >
                                                                      <HTMLEditor
                                                                          value={
                                                                              survey.appearance
                                                                                  .thankYouMessageDescription
                                                                          }
                                                                          onChange={(val) =>
                                                                              setSurveyValue('appearance', {
                                                                                  ...survey.appearance,
                                                                                  thankYouMessageDescription: val,
                                                                              })
                                                                          }
                                                                          writingHTMLDescription={
                                                                              writingHTMLDescription
                                                                          }
                                                                          setWritingHTMLDescription={
                                                                              setWritingHTMLDescription
                                                                          }
                                                                          textPlaceholder="ex: We really appreciate it."
                                                                      />
                                                                  </PureField>
                                                                  <PureField label="Auto disappear">
                                                                      <LemonCheckbox
                                                                          checked={!!survey.appearance.autoDisappear}
                                                                          onChange={(checked) =>
                                                                              setSurveyValue('appearance', {
                                                                                  ...survey.appearance,
                                                                                  autoDisappear: checked,
                                                                              })
                                                                          }
                                                                      />
                                                                  </PureField>
                                                              </>
                                                          ),
                                                      },
                                                  ]
                                                : []),
                                        ]}
                                    />
                                    <div className="flex gap-2">
                                        {featureFlags[FEATURE_FLAGS.SURVEYS_MULTIPLE_QUESTIONS] && (
                                            <div className="flex items-center gap-2 mt-2">
                                                <LemonButton
                                                    type="secondary"
                                                    className="w-max"
                                                    icon={<IconPlus />}
                                                    sideIcon={
                                                        surveysMultipleQuestionsAvailable ? null : (
                                                            <IconLock className="ml-1 text-base text-muted" />
                                                        )
                                                    }
                                                    disabledReason={
                                                        surveysMultipleQuestionsAvailable
                                                            ? null
                                                            : 'Subscribe to surveys for multiple questions'
                                                    }
                                                    onClick={() => {
                                                        setSurveyValue('questions', [
                                                            ...survey.questions,
                                                            { ...defaultSurveyFieldValues.open.questions[0] },
                                                        ])
                                                        setSelectedQuestion(survey.questions.length)
                                                    }}
                                                >
                                                    Add question
                                                </LemonButton>
                                                {!surveysMultipleQuestionsAvailable && (
                                                    <Link to={'/organization/billing'} target="_blank" targetBlankIcon>
                                                        Subscribe
                                                    </Link>
                                                )}
                                            </div>
                                        )}
                                        {!survey.appearance.displayThankYouMessage && (
                                            <LemonButton
                                                type="secondary"
                                                className="w-max mt-2"
                                                icon={<IconPlus />}
                                                onClick={() => {
                                                    setSurveyValue('appearance', {
                                                        ...survey.appearance,
                                                        displayThankYouMessage: true,
                                                    })
                                                    setSelectedQuestion(survey.questions.length)
                                                }}
                                            >
                                                Add confirmation message
                                            </LemonButton>
                                        )}
                                    </div>
                                </>
                            ),
                        },
                        {
                            key: SurveyEditSection.Presentation,
                            header: 'Presentation',
                            content: (
                                <Field name="type">
                                    {({ onChange, value }) => {
                                        return (
                                            <div className="flex gap-4">
                                                <PresentationTypeCard
                                                    active={value === SurveyType.Popover}
                                                    onClick={() => onChange(SurveyType.Popover)}
                                                    title="Popover"
                                                    description="Automatically appears when PostHog JS is installed"
                                                    value={SurveyType.Popover}
                                                >
                                                    <div
                                                        style={{
                                                            transform: 'scale(.8)',
                                                            position: 'absolute',
                                                            top: '-1rem',
                                                            left: '-1rem',
                                                        }}
                                                    >
                                                        <SurveyAppearance
                                                            preview
                                                            type={survey.questions[0].type}
                                                            surveyQuestionItem={survey.questions[0]}
                                                            appearance={{
                                                                ...(survey.appearance || defaultSurveyAppearance),
                                                                ...(survey.questions.length > 1
                                                                    ? { submitButtonText: 'Next' }
                                                                    : null),
                                                            }}
                                                        />
                                                    </div>
                                                </PresentationTypeCard>
                                                <PresentationTypeCard
                                                    active={value === SurveyType.API}
                                                    onClick={() => onChange(SurveyType.API)}
                                                    title="API"
                                                    description="Use the PostHog API to show/hide your survey programmatically"
                                                    value={SurveyType.API}
                                                >
                                                    <div className="absolute left-4" style={{ width: 350 }}>
                                                        <SurveyAPIEditor survey={survey} />
                                                    </div>
                                                </PresentationTypeCard>
                                            </div>
                                        )
                                    }}
                                </Field>
                            ),
                        },
                        ...(survey.type !== SurveyType.API
                            ? [
                                  {
                                      key: SurveyEditSection.Customization,
                                      header: 'Customization',
                                      content: (
                                          <Field name="appearance" label="">
                                              {({ value, onChange }) => (
                                                  <Customization
                                                      appearance={value || defaultSurveyAppearance}
                                                      surveyQuestionItem={survey.questions[0]}
                                                      onAppearanceChange={(appearance) => {
                                                          onChange(appearance)
                                                      }}
                                                  />
                                              )}
                                          </Field>
                                      ),
                                  },
                              ]
                            : []),
                        {
                            key: SurveyEditSection.Targeting,
                            header: 'Targeting',
                            content: (
                                <PureField>
                                    <LemonSelect
                                        onChange={(value) => {
                                            if (value) {
                                                resetTargeting()
                                            } else {
                                                // TRICKY: When attempting to set user match conditions
                                                // we want a proxy value to be set so that the user
                                                // can then edit these, or decide to go back to all user targeting
                                                setSurveyValue('conditions', { url: '' })
                                            }
                                        }}
                                        value={!hasTargetingSet}
                                        options={[
                                            { label: 'All users', value: true },
                                            { label: 'Users who match...', value: false },
                                        ]}
                                    />
                                    {!hasTargetingSet ? (
                                        <span className="text-muted">
                                            Survey <b>will be released to everyone</b>
                                        </span>
                                    ) : (
                                        <>
                                            <Field
                                                name="linked_flag_id"
                                                label="Link feature flag (optional)"
                                                info={
                                                    <>
                                                        Connecting to a feature flag will automatically enable this
                                                        survey for everyone in the feature flag.
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
                                                                onClick={() => onChange(null)}
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
                                                            info="Targeting by regex or exact match requires at least version 1.82 of posthog-js"
                                                        >
                                                            <div className="flex flex-row gap-2 items-center">
                                                                URL
                                                                <LemonSelect
                                                                    value={
                                                                        value?.urlMatchType ||
                                                                        SurveyUrlMatchType.Contains
                                                                    }
                                                                    onChange={(matchTypeVal) => {
                                                                        onChange({
                                                                            ...value,
                                                                            urlMatchType: matchTypeVal,
                                                                        })
                                                                    }}
                                                                    data-attr="survey-url-matching-type"
                                                                    options={Object.keys(SurveyUrlMatchTypeLabels).map(
                                                                        (key) => ({
                                                                            label: SurveyUrlMatchTypeLabels[key],
                                                                            value: key,
                                                                        })
                                                                    )}
                                                                />
                                                                <LemonInput
                                                                    value={value?.url}
                                                                    onChange={(urlVal) =>
                                                                        onChange({ ...value, url: urlVal })
                                                                    }
                                                                    placeholder="ex: https://app.posthog.com"
                                                                    fullWidth
                                                                />
                                                            </div>
                                                        </PureField>
                                                        <PureField label="CSS selector matches:">
                                                            <LemonInput
                                                                value={value?.selector}
                                                                onChange={(selectorVal) =>
                                                                    onChange({ ...value, selector: selectorVal })
                                                                }
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
                                                                                    value?.seenSurveyWaitPeriodInDays ||
                                                                                    30,
                                                                            })
                                                                        } else {
                                                                            const {
                                                                                seenSurveyWaitPeriodInDays,
                                                                                ...rest
                                                                            } = value || {}
                                                                            onChange(rest)
                                                                        }
                                                                    }}
                                                                />
                                                                Do not display this survey to users who have already
                                                                seen a survey in the last
                                                                <LemonInput
                                                                    type="number"
                                                                    size="small"
                                                                    min={0}
                                                                    value={value?.seenSurveyWaitPeriodInDays}
                                                                    onChange={(val) => {
                                                                        if (val !== undefined && val > 0) {
                                                                            onChange({
                                                                                ...value,
                                                                                seenSurveyWaitPeriodInDays: val,
                                                                            })
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
                                                <BindLogic
                                                    logic={featureFlagLogic}
                                                    props={{ id: survey.targeting_flag?.id || 'new' }}
                                                >
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
                                        </>
                                    )}
                                </PureField>
                            ),
                        },
                    ]}
                />
            </div>
            <LemonDivider vertical />
            <div className="max-w-80 mx-4 flex flex-col items-center h-full w-full sticky top-0 pt-8">
                <SurveyFormAppearance
                    activePreview={selectedQuestion || 0}
                    survey={survey}
                    setActivePreview={(preview) => setSelectedQuestion(preview)}
                />
            </div>
        </div>
    )
}

export function HTMLEditor({
    value,
    onChange,
    writingHTMLDescription,
    setWritingHTMLDescription,
    textPlaceholder,
}: {
    value?: string
    onChange: (value: any) => void
    writingHTMLDescription: boolean
    setWritingHTMLDescription: (writingHTML: boolean) => void
    textPlaceholder?: string
}): JSX.Element {
    const { surveysHTMLAvailable } = useValues(surveysLogic)
    return (
        <>
            <LemonTabs
                activeKey={writingHTMLDescription ? 'html' : 'text'}
                onChange={(key) => setWritingHTMLDescription(key === 'html')}
                tabs={[
                    {
                        key: 'text',
                        label: <span className="text-sm">Text</span>,
                        content: (
                            <LemonTextArea
                                minRows={2}
                                value={value}
                                onChange={(v) => onChange(v)}
                                placeholder={textPlaceholder}
                            />
                        ),
                    },
                    {
                        key: 'html',
                        label: (
                            <div>
                                <span className="text-sm">HTML</span>
                                {!surveysHTMLAvailable && <IconLock className="ml-2" />}
                            </div>
                        ),
                        content: (
                            <div>
                                {surveysHTMLAvailable ? (
                                    <CodeEditor
                                        className="border"
                                        language="html"
                                        value={value}
                                        onChange={(v) => onChange(v ?? '')}
                                        height={150}
                                        options={{
                                            minimap: {
                                                enabled: false,
                                            },
                                            scrollbar: {
                                                alwaysConsumeMouseWheel: false,
                                            },
                                            wordWrap: 'on',
                                            scrollBeyondLastLine: false,
                                            automaticLayout: true,
                                            fixedOverflowWidgets: true,
                                            lineNumbers: 'off',
                                            glyphMargin: false,
                                            folding: false,
                                        }}
                                    />
                                ) : (
                                    <PayGateMini feature={AvailableFeature.SURVEYS_TEXT_HTML}>
                                        <CodeEditor
                                            className="border"
                                            language="html"
                                            value={value}
                                            onChange={(v) => onChange(v ?? '')}
                                            height={150}
                                            options={{
                                                minimap: {
                                                    enabled: false,
                                                },
                                                scrollbar: {
                                                    alwaysConsumeMouseWheel: false,
                                                },
                                                wordWrap: 'on',
                                                scrollBeyondLastLine: false,
                                                automaticLayout: true,
                                                fixedOverflowWidgets: true,
                                                lineNumbers: 'off',
                                                glyphMargin: false,
                                                folding: false,
                                            }}
                                        />
                                    </PayGateMini>
                                )}
                            </div>
                        ),
                    },
                ]}
            />
            {value && value?.toLowerCase().includes('<script') && (
                <LemonBanner type="warning">
                    Scripts won't run in the survey popover and we'll remove these on save. Use the API question mode to
                    run your own scripts in surveys.
                </LemonBanner>
            )}
        </>
    )
}
