import './EditSurvey.scss'

import { DndContext } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { FlagSelector } from 'lib/components/FlagSelector'
import { Field, PureField } from 'lib/forms/Field'
import { IconCancel, IconDelete, IconLock, IconPlus } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'

import { LinkSurveyQuestion, RatingSurveyQuestion, SurveyQuestion, SurveyType, SurveyUrlMatchType } from '~/types'

import { defaultSurveyAppearance, defaultSurveyFieldValues, SurveyUrlMatchTypeLabels } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { Customization, SurveyAppearance } from './SurveyAppearance'
import { HTMLEditor, PresentationTypeCard } from './SurveyAppearanceUtils'
import { SurveyEditQuestionGroup, SurveyEditQuestionHeader } from './SurveyEditQuestionRow'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { SurveyEditSection, surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'

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
    const { setSurveyValue, setWritingHTMLDescription, resetTargeting, setSelectedQuestion, setSelectedSection } =
        useActions(surveyLogic)
    const { surveysMultipleQuestionsAvailable } = useValues(surveysLogic)
    const sortedItemIds = survey.questions.map((_, idx) => idx.toString())

    function onSortEnd({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void {
        function move(arr: SurveyQuestion[], from: number, to: number): SurveyQuestion[] {
            const clone = [...arr]
            // Remove the element from the array
            const [element] = clone.splice(from, 1)
            // Insert the element at the new position
            clone.splice(to, 0, element)
            return clone.map((child) => ({ ...child }))
        }
        setSurveyValue('questions', move(survey.questions, oldIndex, newIndex))
        setSelectedQuestion(newIndex)
    }

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
                                    <DndContext
                                        onDragEnd={({ active, over }) => {
                                            if (over && active.id !== over.id) {
                                                onSortEnd({
                                                    oldIndex: sortedItemIds.indexOf(active.id.toString()),
                                                    newIndex: sortedItemIds.indexOf(over.id.toString()),
                                                })
                                            }
                                        }}
                                    >
                                        <SortableContext
                                            disabled={survey.questions.length <= 1}
                                            items={sortedItemIds}
                                            strategy={verticalListSortingStrategy}
                                        >
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
                                                                <SurveyEditQuestionHeader
                                                                    index={index}
                                                                    survey={survey}
                                                                    setSelectedQuestion={setSelectedQuestion}
                                                                    setSurveyValue={setSurveyValue}
                                                                />
                                                            ),
                                                            content: (
                                                                <SurveyEditQuestionGroup
                                                                    index={index}
                                                                    key={index}
                                                                    question={question}
                                                                />
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
                                                                                      survey.appearance
                                                                                          .thankYouMessageHeader
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
                                                                              className="mt-3"
                                                                          >
                                                                              <HTMLEditor
                                                                                  value={
                                                                                      survey.appearance
                                                                                          .thankYouMessageDescription
                                                                                  }
                                                                                  onChange={(val) =>
                                                                                      setSurveyValue('appearance', {
                                                                                          ...survey.appearance,
                                                                                          thankYouMessageDescription:
                                                                                              val,
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
                                                                          <PureField className="mt-2">
                                                                              <LemonCheckbox
                                                                                  checked={
                                                                                      !!survey.appearance.autoDisappear
                                                                                  }
                                                                                  label="Auto disappear"
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
                                        </SortableContext>
                                    </DndContext>
                                    <div className="flex gap-2">
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
