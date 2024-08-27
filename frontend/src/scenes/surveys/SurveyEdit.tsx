import './EditSurvey.scss'

import { DndContext } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { IconInfo } from '@posthog/icons'
import { IconLock, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { FlagSelector } from 'lib/components/FlagSelector'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'

import {
    ActionType,
    LinkSurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestion,
    SurveyType,
    SurveyUrlMatchType,
} from '~/types'

import { defaultSurveyAppearance, defaultSurveyFieldValues, SurveyUrlMatchTypeLabels } from './constants'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { HTMLEditor, PresentationTypeCard } from './SurveyAppearanceUtils'
import { Customization, WidgetCustomization } from './SurveyCustomization'
import { SurveyEditQuestionGroup, SurveyEditQuestionHeader } from './SurveyEditQuestionRow'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { ScheduleType, SurveyEditSection, surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'

export default function SurveyEdit(): JSX.Element {
    const {
        survey,
        urlMatchTypeValidationError,
        hasTargetingSet,
        selectedPageIndex,
        selectedSection,
        isEditingSurvey,
        targetingFlagFilters,
        showSurveyRepeatSchedule,
        schedule,
        hasBranchingLogic,
        surveyRepeatedActivationAvailable,
    } = useValues(surveyLogic)
    const {
        setSurveyValue,
        resetTargeting,
        setSelectedPageIndex,
        setSelectedSection,
        setFlagPropertyErrors,
        setSchedule,
        deleteBranchingLogic,
    } = useActions(surveyLogic)
    const {
        surveysMultipleQuestionsAvailable,
        surveysRecurringScheduleAvailable,
        surveysEventsAvailable,
        surveysActionsAvailable,
    } = useValues(surveysLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const sortedItemIds = survey.questions.map((_, idx) => idx.toString())
    const { thankYouMessageDescriptionContentType = null } = survey.appearance ?? {}
    const surveysRecurringScheduleDisabledReason = surveysRecurringScheduleAvailable
        ? undefined
        : 'Upgrade your plan to use repeating surveys'

    if (survey.iteration_count && survey.iteration_count > 0) {
        setSchedule('recurring')
    }

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
                    className="bg-bg-light"
                    panels={[
                        {
                            key: SurveyEditSection.Presentation,
                            header: 'Presentation',
                            content: (
                                <LemonField name="type">
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
                                                        // eslint-disable-next-line react/forbid-dom-props
                                                        style={{
                                                            transform: 'scale(.8)',
                                                            position: 'absolute',
                                                            top: '-1rem',
                                                            left: '-1rem',
                                                        }}
                                                    >
                                                        <SurveyAppearancePreview survey={survey} previewPageIndex={0} />
                                                    </div>
                                                </PresentationTypeCard>
                                                <PresentationTypeCard
                                                    active={value === SurveyType.API}
                                                    onClick={() => onChange(SurveyType.API)}
                                                    title="API"
                                                    description="Use the PostHog API to show/hide your survey programmatically"
                                                    value={SurveyType.API}
                                                >
                                                    <div
                                                        className="absolute left-4"
                                                        // eslint-disable-next-line react/forbid-dom-props
                                                        style={{ width: 350 }}
                                                    >
                                                        <SurveyAPIEditor survey={survey} />
                                                    </div>
                                                </PresentationTypeCard>
                                                {featureFlags[FEATURE_FLAGS.SURVEYS_WIDGETS] && (
                                                    <PresentationTypeCard
                                                        active={value === SurveyType.Widget}
                                                        onClick={() => onChange(SurveyType.Widget)}
                                                        title="Feedback button"
                                                        description="Set up a survey based on your own custom button or our prebuilt feedback tab"
                                                        value={SurveyType.Widget}
                                                    >
                                                        <LemonTag type="warning" className="uppercase">
                                                            Beta
                                                        </LemonTag>
                                                    </PresentationTypeCard>
                                                )}
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
                                                        <IconLock className="ml-1 text-base text-muted" />
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
                                              {({ value, onChange }) => (
                                                  <>
                                                      {survey.type === SurveyType.Widget && (
                                                          <>
                                                              <div className="font-bold">
                                                                  Feedback button customization
                                                              </div>
                                                              <WidgetCustomization
                                                                  appearance={value || defaultSurveyAppearance}
                                                                  onAppearanceChange={(appearance) => {
                                                                      onChange(appearance)
                                                                  }}
                                                              />
                                                              <LemonDivider className="mt-4" />
                                                              <div className="font-bold">Survey customization</div>
                                                          </>
                                                      )}
                                                      <Customization
                                                          appearance={value || defaultSurveyAppearance}
                                                          surveyQuestionItem={survey.questions[0]}
                                                          onAppearanceChange={(appearance) => {
                                                              onChange(appearance)
                                                          }}
                                                      />
                                                  </>
                                              )}
                                          </LemonField>
                                      ),
                                  },
                              ]
                            : []),
                        {
                            key: SurveyEditSection.DisplayConditions,
                            header: 'Display conditions',
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
                                            { label: 'Users who match all of the following...', value: false },
                                        ]}
                                    />
                                    {!hasTargetingSet ? (
                                        <span className="text-muted">
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
                                                    <div className="flex">
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
                                                                Don't show to users who saw a survey within the last
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
                                                                {value?.seenSurveyWaitPeriodInDays === 1
                                                                    ? 'day'
                                                                    : 'days'}
                                                                .
                                                            </div>
                                                        </LemonField.Pure>
                                                    </>
                                                )}
                                            </LemonField>
                                            <LemonField.Pure label="User properties">
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
                                                                            rollout_percentage: undefined,
                                                                            variant: null,
                                                                        },
                                                                    ],
                                                                    multivariate: null,
                                                                    payloads: {},
                                                                })
                                                                setSurveyValue('remove_targeting_flag', false)
                                                            }}
                                                        >
                                                            Add user targeting
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
                                                                />
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
                                            </LemonField.Pure>
                                            {featureFlags[FEATURE_FLAGS.SURVEYS_EVENTS] && surveysEventsAvailable && (
                                                <LemonField.Pure
                                                    label="User sends events"
                                                    info="Note that these events are only observed, and activate this survey, in the current user session."
                                                >
                                                    <>
                                                        <EventSelect
                                                            filterGroupTypes={[TaxonomicFilterGroupType.CustomEvents]}
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
                            content: (
                                <>
                                    <LemonField name="responses_limit">
                                        {({ onChange, value }) => {
                                            return (
                                                <div className="flex flex-row gap-2 items-center">
                                                    <LemonCheckbox
                                                        checked={!!value}
                                                        onChange={(checked) => {
                                                            const newResponsesLimit = checked ? 100 : null
                                                            onChange(newResponsesLimit)
                                                        }}
                                                    />
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
                                    {featureFlags[FEATURE_FLAGS.SURVEYS_RECURRING] && (
                                        <div className="mt-2">
                                            <h4> How often should we show this survey? </h4>
                                            <LemonField.Pure>
                                                <LemonRadio
                                                    value={schedule}
                                                    onChange={(newValue) => {
                                                        setSchedule(newValue as ScheduleType)
                                                        if (newValue === 'once') {
                                                            setSurveyValue('iteration_count', 0)
                                                            setSurveyValue('iteration_frequency_days', 0)
                                                        }
                                                    }}
                                                    options={[
                                                        {
                                                            value: 'once',
                                                            label: 'Once',
                                                            'data-attr': 'survey-iteration-frequency-days',
                                                        },
                                                        {
                                                            value: 'recurring',
                                                            label: 'Repeat on a Schedule',
                                                            'data-attr': 'survey-iteration-frequency-days',
                                                            disabledReason: surveysRecurringScheduleDisabledReason,
                                                        },
                                                    ]}
                                                />
                                            </LemonField.Pure>

                                            {showSurveyRepeatSchedule && (
                                                <div className="flex flex-row gap-2 items-center mt-2 ml-5">
                                                    Repeat this survey{' '}
                                                    <LemonField name="iteration_count">
                                                        {({ onChange, value }) => {
                                                            return (
                                                                <LemonInput
                                                                    type="number"
                                                                    data-attr="survey-iteration-count"
                                                                    size="small"
                                                                    min={1}
                                                                    value={value || 1}
                                                                    onChange={(newValue) => {
                                                                        if (newValue && newValue > 0) {
                                                                            onChange(newValue)
                                                                        } else {
                                                                            onChange(null)
                                                                        }
                                                                    }}
                                                                    className="w-16"
                                                                />
                                                            )
                                                        }}
                                                    </LemonField>{' '}
                                                    times, once every
                                                    <LemonField name="iteration_frequency_days">
                                                        {({ onChange, value }) => {
                                                            return (
                                                                <LemonInput
                                                                    type="number"
                                                                    data-attr="survey-iteration-frequency-days"
                                                                    size="small"
                                                                    min={1}
                                                                    value={value || 90}
                                                                    onChange={(newValue) => {
                                                                        if (newValue && newValue > 0) {
                                                                            onChange(newValue)
                                                                        } else {
                                                                            onChange(null)
                                                                        }
                                                                    }}
                                                                    className="w-16"
                                                                />
                                                            )
                                                        }}
                                                    </LemonField>{' '}
                                                    days
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </>
                            ),
                        },
                    ]}
                />
            </div>
            <LemonDivider vertical />
            <div className="max-w-80 mx-4 flex flex-col items-center h-full w-full sticky top-0 pt-16">
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
