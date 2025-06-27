import './EditSurvey.scss'

import { DndContext } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { IconInfo, IconLock, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonCalendarSelect,
    LemonCheckbox,
    LemonCollapse,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTextArea,
    Link,
    Popover,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { FlagSelector } from 'lib/components/FlagSelector'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { formatDate } from 'lib/utils'
import { useState } from 'react'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { Customization } from 'scenes/surveys/survey-appearance/SurveyCustomization'
import { SurveyRepeatSchedule } from 'scenes/surveys/SurveyRepeatSchedule'
import { SurveyResponsesCollection } from 'scenes/surveys/SurveyResponsesCollection'
import { SurveyWidgetCustomization } from 'scenes/surveys/SurveyWidgetCustomization'
import { sanitizeSurveyAppearance, validateSurveyAppearance } from 'scenes/surveys/utils'

import { actionsModel } from '~/models/actionsModel'
import { getPropertyKey } from '~/taxonomy/helpers'
import {
    ActionType,
    LinkSurveyQuestion,
    PropertyFilterType,
    PropertyOperator,
    RatingSurveyQuestion,
    SurveyMatchType,
    SurveyQuestion,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import { defaultSurveyFieldValues, SurveyMatchTypeLabels } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { HTMLEditor, PresentationTypeCard } from './SurveyAppearanceUtils'
import { SurveyEditQuestionGroup, SurveyEditQuestionHeader } from './SurveyEditQuestionRow'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { DataCollectionType, SurveyEditSection, surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'

function SurveyCompletionConditions(): JSX.Element {
    const { survey, dataCollectionType, isAdaptiveLimitFFEnabled } = useValues(surveyLogic)
    const { setSurveyValue, resetSurveyResponseLimits, resetSurveyAdaptiveSampling, setDataCollectionType } =
        useActions(surveyLogic)
    const { surveysRecurringScheduleAvailable } = useValues(surveysLogic)
    const [visible, setVisible] = useState(false)

    const surveyLimitOptions: LemonRadioOption<DataCollectionType>[] = [
        {
            value: 'until_stopped',
            label: 'Keep collecting responses until the survey is stopped',
            'data-attr': 'survey-collection-until-stopped',
        },
        {
            value: 'until_limit',
            label: 'Stop displaying the survey after reaching a certain number of completed surveys',
            'data-attr': 'survey-collection-until-limit',
        },
    ]

    if (isAdaptiveLimitFFEnabled) {
        surveyLimitOptions.push({
            value: 'until_adaptive_limit',
            label: 'Collect a certain number of surveys per day, week or month',
            'data-attr': 'survey-collection-until-adaptive-limit',
            disabledReason: surveysRecurringScheduleAvailable
                ? undefined
                : 'Upgrade your plan to use an adaptive limit on survey responses',
        } as unknown as LemonRadioOption<DataCollectionType>)
    }

    return (
        <div className="deprecated-space-y-4">
            <div>
                <h3>How long would you like to collect survey responses? </h3>
                <LemonField.Pure>
                    <LemonRadio
                        value={dataCollectionType}
                        onChange={(newValue: DataCollectionType) => {
                            if (newValue === 'until_limit') {
                                resetSurveyAdaptiveSampling()
                                setSurveyValue('responses_limit', survey.responses_limit || 100)
                            } else if (newValue === 'until_adaptive_limit') {
                                resetSurveyResponseLimits()
                                setSurveyValue('response_sampling_interval', survey.response_sampling_interval || 1)
                                setSurveyValue(
                                    'response_sampling_interval_type',
                                    survey.response_sampling_interval_type || 'month'
                                )
                                setSurveyValue('response_sampling_limit', survey.response_sampling_limit || 100)
                                setSurveyValue(
                                    'response_sampling_start_date',
                                    survey.response_sampling_start_date || dayjs()
                                )
                            } else {
                                resetSurveyResponseLimits()
                                resetSurveyAdaptiveSampling()
                            }
                            setDataCollectionType(newValue)
                        }}
                        options={surveyLimitOptions}
                    />
                </LemonField.Pure>
            </div>
            {dataCollectionType == 'until_adaptive_limit' && (
                <LemonField.Pure>
                    <div className="flex flex-row gap-2 items-center ml-5">
                        Starting on{' '}
                        <Popover
                            actionable
                            overlay={
                                <LemonCalendarSelect
                                    value={dayjs(survey.response_sampling_start_date)}
                                    onChange={(value) => {
                                        setSurveyValue('response_sampling_start_date', value)
                                        setVisible(false)
                                    }}
                                    showTimeToggle={false}
                                    onClose={() => setVisible(false)}
                                />
                            }
                            visible={visible}
                            onClickOutside={() => setVisible(false)}
                        >
                            <LemonButton type="secondary" onClick={() => setVisible(!visible)}>
                                {formatDate(dayjs(survey.response_sampling_start_date || ''))}
                            </LemonButton>
                        </Popover>
                        , capture up to
                        <LemonInput
                            type="number"
                            size="small"
                            min={1}
                            onChange={(newValue) => {
                                setSurveyValue('response_sampling_limit', newValue)
                            }}
                            value={survey.response_sampling_limit || 0}
                        />
                        responses, every
                        <LemonInput
                            type="number"
                            size="small"
                            min={1}
                            onChange={(newValue) => {
                                setSurveyValue('response_sampling_interval', newValue)
                            }}
                            value={survey.response_sampling_interval || 0}
                        />
                        <LemonSelect
                            value={survey.response_sampling_interval_type}
                            size="small"
                            onChange={(newValue) => {
                                setSurveyValue('response_sampling_interval_type', newValue)
                            }}
                            options={[
                                { value: 'day', label: 'Day(s)' },
                                { value: 'week', label: 'Week(s)' },
                                { value: 'month', label: 'Month(s)' },
                            ]}
                        />
                        <Tooltip title="This is a rough guideline, not an absolute one, so the survey might receive slightly more responses than the limit specifies.">
                            <IconInfo />
                        </Tooltip>
                    </div>
                </LemonField.Pure>
            )}
            {dataCollectionType == 'until_limit' && (
                <LemonField name="responses_limit" className="ml-5">
                    {({ onChange, value }) => {
                        return (
                            <div className="flex flex-row gap-2 items-center">
                                Stop the survey once
                                <LemonInput
                                    type="number"
                                    data-attr="survey-responses-limit-input"
                                    size="small"
                                    min={1}
                                    value={value || NaN}
                                    onChange={(newValue) => {
                                        if (newValue && newValue > 0) {
                                            onChange(newValue)
                                        } else {
                                            onChange(null)
                                        }
                                    }}
                                    className="w-16"
                                />{' '}
                                responses are received.
                                <Tooltip title="This is a rough guideline, not an absolute one, so the survey might receive slightly more responses than the limit specifies.">
                                    <IconInfo />
                                </Tooltip>
                            </div>
                        )
                    }}
                </LemonField>
            )}
            <SurveyRepeatSchedule />
            <SurveyResponsesCollection />
        </div>
    )
}

export default function SurveyEdit(): JSX.Element {
    const {
        survey,
        urlMatchTypeValidationError,
        hasTargetingSet,
        selectedPageIndex,
        selectedSection,
        isEditingSurvey,
        targetingFlagFilters,
        hasBranchingLogic,
        surveyRepeatedActivationAvailable,
        deviceTypesMatchTypeValidationError,
        surveyErrors,
    } = useValues(surveyLogic)
    const {
        setSurveyValue,
        resetTargeting,
        setSelectedPageIndex,
        setSelectedSection,
        setFlagPropertyErrors,
        deleteBranchingLogic,
        setSurveyManualErrors,
    } = useActions(surveyLogic)
    const { surveysMultipleQuestionsAvailable, surveysEventsAvailable, surveysActionsAvailable } =
        useValues(surveysLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const sortedItemIds = survey.questions.map((_, idx) => idx.toString())
    const { thankYouMessageDescriptionContentType = null } = survey.appearance ?? {}
    useMountedLogic(actionsModel)

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
        setSelectedPageIndex(newIndex)
    }

    function removeTargetingFlagFilters(): void {
        setSurveyValue('targeting_flag_filters', null)
        setSurveyValue('targeting_flag', null)
        setSurveyValue('remove_targeting_flag', true)
        setFlagPropertyErrors(null)
    }

    return (
        <div className="flex flex-row gap-4">
            <div className="flex flex-col gap-2 flex-1 SurveyForm">
                <LemonField name="name" label="Name">
                    <LemonInput data-attr="survey-name" />
                </LemonField>
                <LemonField name="description" label="Description (optional)">
                    <LemonTextArea data-attr="survey-description" minRows={2} />
                </LemonField>
                <LemonCollapse
                    activeKey={selectedSection || undefined}
                    onChange={(section) => {
                        setSelectedSection(section)
                    }}
                    className="bg-surface-primary"
                    panels={[
                        {
                            key: SurveyEditSection.Presentation,
                            header: 'Presentation',
                            content: (
                                <LemonField name="type">
                                    {({ onChange, value }) => {
                                        return (
                                            <div className="flex flex-col gap-2">
                                                <div className="flex gap-4">
                                                    <PresentationTypeCard
                                                        active={value === SurveyType.Popover}
                                                        onClick={() => {
                                                            onChange(SurveyType.Popover)
                                                            if (survey.schedule === SurveySchedule.Always) {
                                                                setSurveyValue('schedule', SurveySchedule.Once)
                                                            }
                                                        }}
                                                        title="Popover"
                                                        description="Automatically appears when PostHog JS is installed"
                                                        value={SurveyType.Popover}
                                                    >
                                                        <div className="scale-[0.8] absolute -top-4 -left-4">
                                                            <SurveyAppearancePreview
                                                                survey={survey}
                                                                previewPageIndex={0}
                                                            />
                                                        </div>
                                                    </PresentationTypeCard>
                                                    <PresentationTypeCard
                                                        active={value === SurveyType.API}
                                                        onClick={() => {
                                                            onChange(SurveyType.API)
                                                            if (survey.schedule === SurveySchedule.Always) {
                                                                setSurveyValue('schedule', SurveySchedule.Once)
                                                            }
                                                        }}
                                                        title="API"
                                                        description="Use the PostHog API to show/hide your survey programmatically"
                                                        value={SurveyType.API}
                                                    >
                                                        <div className="absolute left-4 w-[350px]">
                                                            <SurveyAPIEditor survey={survey} />
                                                        </div>
                                                    </PresentationTypeCard>
                                                    <PresentationTypeCard
                                                        active={value === SurveyType.Widget}
                                                        onClick={() => onChange(SurveyType.Widget)}
                                                        title="Feedback button"
                                                        description="Set up a survey based on your own custom button or our prebuilt feedback tab"
                                                        value={SurveyType.Widget}
                                                    >
                                                        <button className="bg-black -rotate-90 py-2 px-3 min-w-[40px] absolute -right-4 -bottom-16">
                                                            Feedback
                                                        </button>
                                                    </PresentationTypeCard>
                                                </div>
                                                {survey.type === SurveyType.Widget && <SurveyWidgetCustomization />}
                                            </div>
                                        )
                                    }}
                                </LemonField>
                            ),
                        },
                        {
                            key: SurveyEditSection.Steps,
                            header: 'Steps',
                            content: (
                                <>
                                    <DndContext
                                        onDragEnd={({ active, over }) => {
                                            if (over && active.id !== over.id) {
                                                const finishDrag = (): void =>
                                                    onSortEnd({
                                                        oldIndex: sortedItemIds.indexOf(active.id.toString()),
                                                        newIndex: sortedItemIds.indexOf(over.id.toString()),
                                                    })

                                                if (hasBranchingLogic) {
                                                    LemonDialog.open({
                                                        title: 'Your survey has active branching logic',
                                                        description: (
                                                            <p className="py-2">
                                                                Rearranging questions will remove your branching logic.
                                                                Are you sure you want to continue?
                                                            </p>
                                                        ),

                                                        primaryButton: {
                                                            children: 'Continue',
                                                            status: 'danger',
                                                            onClick: () => {
                                                                deleteBranchingLogic()
                                                                finishDrag()
                                                            },
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                        },
                                                    })
                                                } else {
                                                    finishDrag()
                                                }
                                            }
                                        }}
                                    >
                                        <SortableContext
                                            disabled={survey.questions.length <= 1}
                                            items={sortedItemIds}
                                            strategy={verticalListSortingStrategy}
                                        >
                                            <LemonCollapse
                                                activeKey={selectedPageIndex === null ? undefined : selectedPageIndex}
                                                onChange={(index) => {
                                                    setSelectedPageIndex(index)
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
                                                            dataAttr: `survey-question-panel-${index}`,
                                                            header: (
                                                                <SurveyEditQuestionHeader
                                                                    index={index}
                                                                    survey={survey}
                                                                    setSelectedPageIndex={setSelectedPageIndex}
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
                                                    ...(survey.appearance?.displayThankYouMessage
                                                        ? [
                                                              {
                                                                  key: survey.questions.length,
                                                                  header: (
                                                                      <div className="flex flex-row w-full items-center justify-between">
                                                                          <b>Confirmation message</b>
                                                                          <LemonButton
                                                                              icon={<IconTrash />}
                                                                              data-attr="delete-survey-confirmation"
                                                                              onClick={(e) => {
                                                                                  const deleteConfirmationMessage =
                                                                                      (): void => {
                                                                                          e.stopPropagation()
                                                                                          setSelectedPageIndex(
                                                                                              survey.questions.length -
                                                                                                  1
                                                                                          )
                                                                                          setSurveyValue('appearance', {
                                                                                              ...survey.appearance,
                                                                                              displayThankYouMessage:
                                                                                                  false,
                                                                                          })
                                                                                      }

                                                                                  if (hasBranchingLogic) {
                                                                                      LemonDialog.open({
                                                                                          title: 'Your survey has active branching logic',
                                                                                          description: (
                                                                                              <p className="py-2">
                                                                                                  Deleting the
                                                                                                  confirmation message
                                                                                                  will remove your
                                                                                                  branching logic. Are
                                                                                                  you sure you want to
                                                                                                  continue?
                                                                                              </p>
                                                                                          ),
                                                                                          primaryButton: {
                                                                                              children: 'Continue',
                                                                                              status: 'danger',
                                                                                              onClick: () => {
                                                                                                  deleteBranchingLogic()
                                                                                                  deleteConfirmationMessage()
                                                                                              },
                                                                                          },
                                                                                          secondaryButton: {
                                                                                              children: 'Cancel',
                                                                                          },
                                                                                      })
                                                                                  } else {
                                                                                      deleteConfirmationMessage()
                                                                                  }
                                                                              }}
                                                                              tooltipPlacement="top-end"
                                                                          />
                                                                      </div>
                                                                  ),
                                                                  content: (
                                                                      <>
                                                                          <LemonField.Pure label="Thank you header">
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
                                                                          </LemonField.Pure>
                                                                          <LemonField.Pure
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
                                                                                          thankYouMessageDescriptionContentType,
                                                                                      })
                                                                                  }
                                                                                  onTabChange={(key) => {
                                                                                      const updatedAppearance = {
                                                                                          ...survey.appearance,
                                                                                          thankYouMessageDescriptionContentType:
                                                                                              key === 'html'
                                                                                                  ? 'html'
                                                                                                  : 'text',
                                                                                      }
                                                                                      setSurveyValue(
                                                                                          'appearance',
                                                                                          updatedAppearance
                                                                                      )
                                                                                  }}
                                                                                  activeTab={
                                                                                      thankYouMessageDescriptionContentType ??
                                                                                      'text'
                                                                                  }
                                                                                  textPlaceholder="ex: We really appreciate it."
                                                                              />
                                                                          </LemonField.Pure>
                                                                          <LemonField.Pure
                                                                              className="mt-2"
                                                                              label="Button text"
                                                                          >
                                                                              <LemonInput
                                                                                  value={
                                                                                      survey.appearance
                                                                                          .thankYouMessageCloseButtonText
                                                                                  }
                                                                                  onChange={(val) =>
                                                                                      setSurveyValue('appearance', {
                                                                                          ...survey.appearance,
                                                                                          thankYouMessageCloseButtonText:
                                                                                              val,
                                                                                      })
                                                                                  }
                                                                                  placeholder="example: Close"
                                                                              />
                                                                          </LemonField.Pure>
                                                                          <LemonField.Pure className="mt-2">
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
                                                                          </LemonField.Pure>
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
                                                data-attr="add-question"
                                                type="secondary"
                                                className="w-max"
                                                icon={<IconPlus />}
                                                sideIcon={
                                                    surveysMultipleQuestionsAvailable ? null : (
                                                        <IconLock className="ml-1 text-base text-secondary" />
                                                    )
                                                }
                                                disabledReason={
                                                    surveysMultipleQuestionsAvailable
                                                        ? null
                                                        : 'Upgrade your plan to get multiple questions'
                                                }
                                                onClick={() => {
                                                    setSurveyValue('questions', [
                                                        ...survey.questions,
                                                        { ...defaultSurveyFieldValues.open.questions[0] },
                                                    ])
                                                    setSelectedPageIndex(survey.questions.length)
                                                }}
                                            >
                                                Add question
                                            </LemonButton>
                                            {!surveysMultipleQuestionsAvailable && (
                                                <Link to="/organization/billing" target="_blank" targetBlankIcon>
                                                    Upgrade
                                                </Link>
                                            )}
                                        </div>
                                        {!survey.appearance?.displayThankYouMessage && (
                                            <LemonButton
                                                type="secondary"
                                                className="w-max mt-2"
                                                icon={<IconPlus />}
                                                onClick={() => {
                                                    setSurveyValue('appearance', {
                                                        ...survey.appearance,
                                                        displayThankYouMessage: true,
                                                    })
                                                    setSelectedPageIndex(survey.questions.length)
                                                }}
                                            >
                                                Add confirmation message
                                            </LemonButton>
                                        )}
                                    </div>
                                </>
                            ),
                        },
                        ...(survey.type !== SurveyType.API
                            ? [
                                  {
                                      key: SurveyEditSection.Customization,
                                      header: 'Customization',
                                      content: (
                                          <LemonField name="appearance" label="">
                                              {({ onChange }) => (
                                                  <Customization
                                                      survey={survey}
                                                      hasBranchingLogic={hasBranchingLogic}
                                                      deleteBranchingLogic={deleteBranchingLogic}
                                                      hasRatingButtons={survey.questions.some(
                                                          (question) => question.type === SurveyQuestionType.Rating
                                                      )}
                                                      hasPlaceholderText={survey.questions.some(
                                                          (question) => question.type === SurveyQuestionType.Open
                                                      )}
                                                      onAppearanceChange={(appearance) => {
                                                          const newAppearance = sanitizeSurveyAppearance({
                                                              ...survey.appearance,
                                                              ...appearance,
                                                          })
                                                          onChange(newAppearance)
                                                          if (newAppearance) {
                                                              setSurveyManualErrors(
                                                                  validateSurveyAppearance(
                                                                      newAppearance,
                                                                      true,
                                                                      survey.type
                                                                  )
                                                              )
                                                          }
                                                      }}
                                                      validationErrors={surveyErrors?.appearance}
                                                  />
                                              )}
                                          </LemonField>
                                      ),
                                  },
                              ]
                            : []),
                        {
                            key: SurveyEditSection.DisplayConditions,
                            header: 'Display conditions',
                            dataAttr: 'survey-display-conditions',
                            content: (
                                <LemonField.Pure>
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
                                            {
                                                label: 'Users who match all of the following...',
                                                value: false,
                                                'data-attr': 'survey-display-conditions-select-users',
                                            },
                                        ]}
                                        data-attr="survey-display-conditions-select"
                                    />
                                    {!hasTargetingSet ? (
                                        <span className="text-secondary">
                                            Survey <b>will be released to everyone</b>
                                        </span>
                                    ) : (
                                        <>
                                            <LemonField
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
                                                    <div
                                                        className="flex"
                                                        data-attr="survey-display-conditions-linked-flag"
                                                    >
                                                        <FlagSelector value={value} onChange={onChange} />
                                                        {value && (
                                                            <LemonButton
                                                                className="ml-2"
                                                                icon={<IconCancel />}
                                                                size="small"
                                                                onClick={() => onChange(null)}
                                                                aria-label="close"
                                                            />
                                                        )}
                                                    </div>
                                                )}
                                            </LemonField>
                                            <LemonField name="conditions">
                                                {({ value, onChange }) => (
                                                    <>
                                                        <LemonField.Pure
                                                            label="URL targeting"
                                                            error={urlMatchTypeValidationError}
                                                            info="Targeting by regex or exact match requires at least version 1.82 of posthog-js"
                                                        >
                                                            <div className="flex flex-row gap-2 items-center">
                                                                URL
                                                                <LemonSelect
                                                                    value={
                                                                        value?.urlMatchType || SurveyMatchType.Contains
                                                                    }
                                                                    onChange={(matchTypeVal) => {
                                                                        onChange({
                                                                            ...value,
                                                                            urlMatchType: matchTypeVal,
                                                                        })
                                                                    }}
                                                                    data-attr="survey-url-matching-type"
                                                                    options={Object.keys(SurveyMatchTypeLabels).map(
                                                                        (key) => ({
                                                                            label: SurveyMatchTypeLabels[key],
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
                                                        </LemonField.Pure>
                                                        <LemonField.Pure
                                                            label="Device Types"
                                                            error={deviceTypesMatchTypeValidationError}
                                                            info={
                                                                <>
                                                                    Add the device types to show the survey on. Possible
                                                                    values: 'Desktop', 'Mobile', 'Tablet'. For the full
                                                                    list and caveats,{' '}
                                                                    <Link to="https://posthog.com/docs/surveys/creating-surveys#display-conditions">
                                                                        check the documentation here
                                                                    </Link>
                                                                    . Requires at least version 1.214 of posthog-js
                                                                </>
                                                            }
                                                        >
                                                            <div className="flex flex-row gap-2 items-center">
                                                                Device Types
                                                                <LemonSelect
                                                                    value={
                                                                        value?.deviceTypesMatchType ||
                                                                        SurveyMatchType.Contains
                                                                    }
                                                                    onChange={(matchTypeVal) => {
                                                                        onChange({
                                                                            ...value,
                                                                            deviceTypesMatchType: matchTypeVal,
                                                                        })
                                                                    }}
                                                                    data-attr="survey-device-types-matching-type"
                                                                    options={Object.keys(SurveyMatchTypeLabels).map(
                                                                        (key) => ({
                                                                            label: SurveyMatchTypeLabels[key],
                                                                            value: key,
                                                                        })
                                                                    )}
                                                                />
                                                                {[
                                                                    SurveyMatchType.Regex,
                                                                    SurveyMatchType.NotRegex,
                                                                ].includes(
                                                                    value?.deviceTypesMatchType ||
                                                                        SurveyMatchType.Contains
                                                                ) ? (
                                                                    <LemonInput
                                                                        value={value?.deviceTypes?.join('|')}
                                                                        onChange={(deviceTypesVal) =>
                                                                            onChange({
                                                                                ...value,
                                                                                deviceTypes: [deviceTypesVal],
                                                                            })
                                                                        }
                                                                        // regex placeholder for device type
                                                                        className="flex-1"
                                                                        placeholder="ex: Desktop|Mobile"
                                                                    />
                                                                ) : (
                                                                    <PropertyValue
                                                                        propertyKey={getPropertyKey(
                                                                            'Device Type',
                                                                            TaxonomicFilterGroupType.EventProperties
                                                                        )}
                                                                        type={PropertyFilterType.Event}
                                                                        onSet={(deviceTypes: string | string[]) => {
                                                                            onChange({
                                                                                ...value,
                                                                                deviceTypes: Array.isArray(deviceTypes)
                                                                                    ? deviceTypes
                                                                                    : [deviceTypes],
                                                                            })
                                                                        }}
                                                                        operator={PropertyOperator.Exact}
                                                                        value={value?.deviceTypes}
                                                                        inputClassName="flex-1"
                                                                    />
                                                                )}
                                                            </div>
                                                        </LemonField.Pure>
                                                        <LemonField.Pure label="CSS selector matches:">
                                                            <LemonInput
                                                                value={value?.selector}
                                                                onChange={(selectorVal) =>
                                                                    onChange({ ...value, selector: selectorVal })
                                                                }
                                                                placeholder="ex: .className or #id"
                                                            />
                                                        </LemonField.Pure>
                                                        <LemonField.Pure
                                                            label="Survey wait period"
                                                            info="Note that this condition will only apply reliably for identified users within a single browser session. Anonymous users or users who switch browsers, use incognito sessions, or log out and log back in may see the survey again. Additionally, responses submitted while a user is anonymous may be associated with their account if they log in during the same session."
                                                        >
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
                                                                Don't show to users who saw any survey in the last
                                                                <LemonInput
                                                                    type="number"
                                                                    size="xsmall"
                                                                    min={0}
                                                                    value={value?.seenSurveyWaitPeriodInDays || NaN}
                                                                    onChange={(val) => {
                                                                        if (val !== undefined && val > 0) {
                                                                            onChange({
                                                                                ...value,
                                                                                seenSurveyWaitPeriodInDays: val,
                                                                            })
                                                                        } else {
                                                                            onChange({
                                                                                ...value,
                                                                                seenSurveyWaitPeriodInDays: null,
                                                                            })
                                                                        }
                                                                    }}
                                                                    className="w-12"
                                                                />{' '}
                                                                {value?.seenSurveyWaitPeriodInDays === 1 ? (
                                                                    <span>day.</span>
                                                                ) : (
                                                                    <span>days.</span>
                                                                )}
                                                            </div>
                                                        </LemonField.Pure>
                                                    </>
                                                )}
                                            </LemonField>
                                            <LemonField.Pure label="Properties">
                                                <BindLogic
                                                    logic={featureFlagLogic}
                                                    props={{ id: survey.targeting_flag?.id || 'new' }}
                                                >
                                                    {!targetingFlagFilters && (
                                                        <LemonButton
                                                            type="secondary"
                                                            className="w-max"
                                                            onClick={() => {
                                                                setSurveyValue('targeting_flag_filters', {
                                                                    groups: [
                                                                        {
                                                                            properties: [],
                                                                            rollout_percentage: 100,
                                                                            variant: null,
                                                                        },
                                                                    ],
                                                                    multivariate: null,
                                                                    payloads: {},
                                                                })
                                                                setSurveyValue('remove_targeting_flag', false)
                                                            }}
                                                        >
                                                            Add property targeting
                                                        </LemonButton>
                                                    )}
                                                    {targetingFlagFilters && (
                                                        <>
                                                            <div className="mt-2">
                                                                <FeatureFlagReleaseConditions
                                                                    id={String(survey.targeting_flag?.id) || 'new'}
                                                                    excludeTitle={true}
                                                                    filters={targetingFlagFilters}
                                                                    onChange={(filters, errors) => {
                                                                        setFlagPropertyErrors(errors)
                                                                        setSurveyValue(
                                                                            'targeting_flag_filters',
                                                                            filters
                                                                        )
                                                                    }}
                                                                    showTrashIconWithOneCondition
                                                                    removedLastConditionCallback={
                                                                        removeTargetingFlagFilters
                                                                    }
                                                                />
                                                            </div>
                                                            <LemonButton
                                                                type="secondary"
                                                                status="danger"
                                                                className="w-max"
                                                                onClick={removeTargetingFlagFilters}
                                                            >
                                                                Remove all property targeting
                                                            </LemonButton>
                                                        </>
                                                    )}
                                                </BindLogic>
                                            </LemonField.Pure>
                                            {surveysEventsAvailable && (
                                                <LemonField.Pure
                                                    label="User sends events"
                                                    info="It only triggers when the event is captured in the current user session and using the PostHog SDK."
                                                >
                                                    <>
                                                        <EventSelect
                                                            filterGroupTypes={[
                                                                TaxonomicFilterGroupType.CustomEvents,
                                                                TaxonomicFilterGroupType.Events,
                                                            ]}
                                                            allowNonCapturedEvents
                                                            onChange={(includedEvents) => {
                                                                setSurveyValue('conditions', {
                                                                    ...survey.conditions,
                                                                    events: {
                                                                        values: includedEvents.map((e) => {
                                                                            return { name: e }
                                                                        }),
                                                                    },
                                                                })
                                                            }}
                                                            selectedEvents={
                                                                survey.conditions?.events?.values?.length !=
                                                                    undefined &&
                                                                survey.conditions?.events?.values?.length > 0
                                                                    ? survey.conditions?.events?.values.map(
                                                                          (v) => v.name
                                                                      )
                                                                    : []
                                                            }
                                                            addElement={
                                                                <LemonButton
                                                                    size="small"
                                                                    type="secondary"
                                                                    icon={<IconPlus />}
                                                                    sideIcon={null}
                                                                >
                                                                    Add event
                                                                </LemonButton>
                                                            }
                                                        />
                                                        {surveyRepeatedActivationAvailable && (
                                                            <div className="flex flex-row gap-2 items-center">
                                                                Survey display frequency
                                                                <LemonSelect
                                                                    onChange={(value) => {
                                                                        setSurveyValue('conditions', {
                                                                            ...survey.conditions,
                                                                            events: {
                                                                                ...survey.conditions?.events,
                                                                                repeatedActivation: value,
                                                                            },
                                                                        })
                                                                    }}
                                                                    value={
                                                                        survey.conditions?.events?.repeatedActivation ||
                                                                        false
                                                                    }
                                                                    options={[
                                                                        {
                                                                            label: 'Just once',
                                                                            value: false,
                                                                        },
                                                                        {
                                                                            label: 'Every time any of the above events are captured',
                                                                            value: true,
                                                                        },
                                                                    ]}
                                                                />
                                                            </div>
                                                        )}
                                                    </>
                                                </LemonField.Pure>
                                            )}
                                            {featureFlags[FEATURE_FLAGS.SURVEYS_ACTIONS] && surveysActionsAvailable && (
                                                <LemonField.Pure
                                                    label="User performs actions"
                                                    info="Note that these actions are only observed, and activate this survey, in the current user session."
                                                >
                                                    <EventSelect
                                                        filterGroupTypes={[TaxonomicFilterGroupType.Actions]}
                                                        onItemChange={(items: ActionType[]) => {
                                                            setSurveyValue('conditions', {
                                                                ...survey.conditions,
                                                                actions: {
                                                                    values: items.map((e) => {
                                                                        return { id: e.id, name: e.name }
                                                                    }),
                                                                },
                                                            })
                                                        }}
                                                        selectedItems={
                                                            survey.conditions?.actions?.values &&
                                                            survey.conditions?.actions?.values.length > 0
                                                                ? survey.conditions?.actions?.values
                                                                : []
                                                        }
                                                        selectedEvents={
                                                            survey.conditions?.actions?.values?.map((v) => v.name) ?? []
                                                        }
                                                        addElement={
                                                            <LemonButton
                                                                size="small"
                                                                type="secondary"
                                                                icon={<IconPlus />}
                                                                sideIcon={null}
                                                            >
                                                                Add action
                                                            </LemonButton>
                                                        }
                                                    />
                                                </LemonField.Pure>
                                            )}
                                        </>
                                    )}
                                </LemonField.Pure>
                            ),
                        },
                        {
                            key: SurveyEditSection.CompletionConditions,
                            header: 'Completion conditions',
                            content: <SurveyCompletionConditions />,
                        },
                    ]}
                />
            </div>
            <LemonDivider vertical />
            <div className="flex flex-col h-full sticky top-0 max-w-1/2 overflow-auto">
                <SurveyFormAppearance
                    previewPageIndex={selectedPageIndex || 0}
                    survey={survey}
                    handleSetSelectedPageIndex={(pageIndex) => setSelectedPageIndex(pageIndex)}
                    isEditingSurvey={isEditingSurvey}
                />
            </div>
        </div>
    )
}
