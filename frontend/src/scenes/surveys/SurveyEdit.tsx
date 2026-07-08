import './EditSurvey.scss'

import { DndContext } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconGitBranch, IconInfo, IconPlus, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCalendarSelect,
    LemonCheckbox,
    LemonCollapse,
    LemonDialog,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    Link,
    Popover,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { FlagSelector } from 'lib/components/FlagSelector'
import { ANY_VARIANT, variantOptions } from 'lib/components/IngestionControls/triggers/FlagTrigger/VariantSelector'
import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { formatDate } from 'lib/utils/datetime'
import { ValueOf } from 'lib/utils/types'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { Customization } from 'scenes/surveys/survey-appearance/SurveyCustomization'
import { SurveyActionTrigger } from 'scenes/surveys/SurveyActionTrigger'
import { SurveyCancelEventTrigger, SurveyEventTrigger } from 'scenes/surveys/SurveyEventTrigger'
import { SurveyRepeatSchedule } from 'scenes/surveys/SurveyRepeatSchedule'
import { SurveyResponsesCollection } from 'scenes/surveys/SurveyResponsesCollection'
import { SurveyTranslations } from 'scenes/surveys/SurveyTranslations'
import { getSurveyWithTranslatedContent } from 'scenes/surveys/surveyTranslationUtils'
import { SurveyWidgetCustomization } from 'scenes/surveys/SurveyWidgetCustomization'
import { sanitizeSurveyAppearance, validateSurveyAppearance } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { actionsModel } from '~/models/actionsModel'
import { getPropertyKey } from '~/taxonomy/helpers'
import {
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

import { SurveyBranchingFlowModal } from './branching-flow/SurveyBranchingFlowModal'
import { SURVEY_TYPE_LABEL_MAP, SurveyMatchTypeLabels, defaultSurveyFieldValues } from './constants'
import { COMMON_LANGUAGES, getBaseLanguage, getSurveyLanguageName } from './language'
import { SurveyAPIEditor } from './SurveyAPIEditor'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { HTMLEditor, PresentationTypeCard } from './SurveyAppearanceUtils'
import { SurveyEditQuestionGroup, SurveyEditQuestionHeader } from './SurveyEditQuestionRow'
import { SurveyFormAppearance } from './SurveyFormAppearance'
import { DataCollectionType, SurveyEditSection, surveyLogic } from './surveyLogic'
import { surveysLogic } from './surveysLogic'
import { canUseSurveyWizard } from './utils'

function SurveyCompletionConditions(): JSX.Element {
    const { survey, dataCollectionType, isAdaptiveLimitFFEnabled } = useValues(surveyLogic)
    const { setSurveyValue, resetSurveyResponseLimits, resetSurveyAdaptiveSampling, setDataCollectionType } =
        useActions(surveyLogic)
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
            {survey.type !== SurveyType.ExternalSurvey && <SurveyRepeatSchedule />}
            <SurveyResponsesCollection />
        </div>
    )
}

// Helper to format field names for display
function formatFieldName(field: string): string {
    const fieldNameMap: Record<string, string> = {
        name: 'Survey name',
        description: 'Survey description',
        thankYouMessageHeader: 'Thank you message header',
        thankYouMessageDescription: 'Thank you message description',
        thankYouMessageCloseButtonText: 'Thank you close button text',
        question: 'Question text',
        buttonText: 'Button text',
        lowerBoundLabel: 'Lower bound label',
        upperBoundLabel: 'Upper bound label',
        link: 'Link URL',
    }

    // Handle choices[n] format
    const choiceMatch = field.match(/^choices\[(\d+)\]$/)
    if (choiceMatch) {
        return `Choice ${parseInt(choiceMatch[1]) + 1}`
    }

    return fieldNameMap[field] || field
}

export default function SurveyEdit({ id }: { id: string }): JSX.Element {
    const {
        survey,
        editingLanguage,
        urlMatchTypeValidationError,
        hasTargetingSet,
        selectedPageIndex,
        selectedSection,
        isEditingSurvey,
        targetingFlagFilters,
        hasBranchingLogic,
        deviceTypesMatchTypeValidationError,
        surveyErrors,
        user,
        surveyLoading,
        translationValidationErrors,
        hasTranslationValidationErrors,
        translationErrorsByQuestion,
        translationErrorsForField,
        aiGeneratedTranslationFields,
    } = useValues(surveyLogic)
    const {
        setSurveyValue,
        resetTargeting,
        setSelectedPageIndex,
        setSelectedSection,
        setEditingLanguage,
        setFlagPropertyErrors,
        deleteBranchingLogic,
        moveQuestion,
        setSurveyManualErrors,
        editingSurvey,
        loadSurvey,
        clearAiGeneratedTranslationField,
    } = useActions(surveyLogic)
    const { setPreferredEditor } = useActions(surveysLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const surveyTranslationsEnabled = !!featureFlags[FEATURE_FLAGS.SURVEYS_TRANSLATIONS]
    const hostedEditorEnabled = !!featureFlags[FEATURE_FLAGS.SURVEYS_HOSTED_EDITOR]
    const canConvertToHosted = hostedEditorEnabled && survey.type !== SurveyType.ExternalSurvey

    const convertToHostedSurvey = (): void => {
        LemonDialog.open({
            title: 'Convert to hosted survey?',
            description: (
                <p className="py-2">
                    This keeps the questions and style, then switches the editor to the hosted-survey setup. Display
                    conditions and in-app placement settings won't apply.
                </p>
            ),
            primaryButton: {
                children: 'Convert',
                onClick: () => {
                    setSurveyValue('type', SurveyType.ExternalSurvey)
                    setSelectedPageIndex(0)
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }
    const activeEditingLanguage = surveyTranslationsEnabled ? editingLanguage : null
    const surveyTranslations = survey.translations ?? {}
    const hasActualTranslations = !!(
        (survey.translations && Object.keys(survey.translations).length > 0) ||
        (survey.questions && survey.questions.some((q) => q.translations && Object.keys(q.translations).length > 0))
    )
    const hasActiveTranslationValidationErrors = surveyTranslationsEnabled && hasTranslationValidationErrors
    const activeTranslationValidationErrors = surveyTranslationsEnabled ? translationValidationErrors : []
    const hasVisibleTranslationValidationErrors = hasActiveTranslationValidationErrors && hasActualTranslations
    const previewSurvey = useMemo(
        () => getSurveyWithTranslatedContent(survey, activeEditingLanguage),
        [survey, activeEditingLanguage]
    )
    const sortedItemIds = survey.questions.map((_, idx) => idx.toString())
    const { thankYouMessageDescriptionContentType = null } = survey.appearance ?? {}
    useMountedLogic(actionsModel)

    const [showFlowModal, setShowFlowModal] = useState(false)

    // Auto-expand Steps panel when a language is selected for translation.
    useEffect(() => {
        if (!surveyTranslationsEnabled && editingLanguage !== null) {
            setEditingLanguage(null)
            return
        }

        if (activeEditingLanguage !== null) {
            setSelectedSection(SurveyEditSection.Steps)
        }
    }, [activeEditingLanguage, editingLanguage, setEditingLanguage, setSelectedSection, surveyTranslationsEnabled])

    const handleCancelClick = (): void => {
        editingSurvey(false)
        if (id === 'new') {
            router.actions.push(urls.surveys())
        } else {
            loadSurvey()
        }
    }

    function onSortEnd({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void {
        moveQuestion(oldIndex, newIndex)
        setSelectedPageIndex(newIndex)
    }

    function removeTargetingFlagFilters(): void {
        setSurveyValue('targeting_flag_filters', null)
        setSurveyValue('targeting_flag', null)
        setSurveyValue('remove_targeting_flag', true)
        setFlagPropertyErrors(null)
    }

    const getFieldError = (
        fieldKey: string
    ): { language: string; questionIndex: number; field: string; error: string } | undefined => {
        return translationErrorsForField(-1, fieldKey)
    }

    const getFieldErrorClass = (fieldKey: string): string => {
        const fieldError = getFieldError(fieldKey)
        const aiGenerated = isAiGeneratedField(fieldKey)
        return [
            fieldError ? 'border border-warning hover:border-primary' : '',
            aiGenerated ? 'border border-dashed border-accent bg-accent-highlight-secondary' : '',
        ]
            .filter(Boolean)
            .join(' ')
    }

    const isAiGeneratedField = (fieldKey: string): boolean =>
        !!activeEditingLanguage &&
        aiGeneratedTranslationFields.includes(`translations.${activeEditingLanguage}.${fieldKey}`)

    const getFieldLabel = (label: string, fieldKey: string): JSX.Element | string =>
        isAiGeneratedField(fieldKey) ? (
            <span className="flex items-center gap-1">
                <span>{label}</span>
                <LemonTag type="highlight">AI draft</LemonTag>
            </span>
        ) : (
            label
        )

    const getConfirmationMessageErrors = (): number => {
        let count = 0
        if (getFieldError('thankYouMessageHeader')) {
            count++
        }
        if (getFieldError('thankYouMessageDescription')) {
            count++
        }
        if (getFieldError('thankYouMessageCloseButtonText')) {
            count++
        }
        return count
    }

    return (
        <SceneContent>
            <div
                className={`flex flex-col gap-y-4 ${
                    activeEditingLanguage || hasVisibleTranslationValidationErrors ? 'mt-1' : ''
                }`}
            >
                <SceneTitleSection
                    name={
                        activeEditingLanguage ? (survey.translations?.[activeEditingLanguage]?.name ?? '') : survey.name
                    }
                    description={activeEditingLanguage ? null : survey.description}
                    resourceType={{
                        type: 'survey',
                    }}
                    canEdit
                    onNameChange={(name) => {
                        if (activeEditingLanguage) {
                            clearAiGeneratedTranslationField(`translations.${activeEditingLanguage}.name`)
                            setSurveyValue('translations', {
                                ...surveyTranslations,
                                [activeEditingLanguage]: {
                                    ...survey.translations?.[activeEditingLanguage],
                                    name,
                                },
                            })
                        } else {
                            setSurveyValue('name', name)
                        }
                    }}
                    onDescriptionChange={(description) => {
                        setSurveyValue('description', description)
                    }}
                    renameDebounceMs={0}
                    forceEdit
                    actions={
                        <>
                            {canUseSurveyWizard(survey) && (
                                <LemonButton
                                    data-attr="switch-to-wizard"
                                    type="tertiary"
                                    size="small"
                                    to={urls.surveyWizard(id)}
                                    onClick={() => setPreferredEditor('guided')}
                                >
                                    Guided editor
                                </LemonButton>
                            )}
                            {canConvertToHosted && (
                                <LemonButton
                                    data-attr="convert-to-hosted-survey"
                                    type="tertiary"
                                    size="small"
                                    onClick={convertToHostedSurvey}
                                >
                                    Convert to hosted
                                </LemonButton>
                            )}
                            <LemonButton
                                data-attr="cancel-survey"
                                type="secondary"
                                loading={surveyLoading}
                                onClick={handleCancelClick}
                                size="small"
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="save-survey"
                                htmlType="submit"
                                loading={surveyLoading}
                                form="survey"
                                size="small"
                                disabledReason={
                                    hasVisibleTranslationValidationErrors
                                        ? 'Cannot save: please fix translation validation errors below'
                                        : undefined
                                }
                            >
                                {id === 'new' ? 'Save as draft' : 'Save'}
                            </LemonButton>
                        </>
                    }
                />
                <div className="sticky top-[34px] z-[100] bg-bg-3000">
                    {(() => {
                        const shouldShowValidationErrors = hasVisibleTranslationValidationErrors

                        if (shouldShowValidationErrors) {
                            return (
                                <LemonCollapse
                                    embedded
                                    className="my-2 bg-warning-highlight rounded"
                                    panels={[
                                        {
                                            key: 'validation-errors',
                                            header: {
                                                children: (
                                                    <span className="text-sm">
                                                        ⚠️ Translation validation issues (
                                                        {activeTranslationValidationErrors.length})
                                                    </span>
                                                ),
                                                className: 'bg-warning-highlight',
                                            },
                                            content: (
                                                <div className="text-sm">
                                                    {(() => {
                                                        const errorsByLanguage =
                                                            activeTranslationValidationErrors.reduce(
                                                                (acc, error) => {
                                                                    const lang = error.language
                                                                    if (!acc[lang]) {
                                                                        acc[lang] = []
                                                                    }
                                                                    acc[lang].push(error)
                                                                    return acc
                                                                },
                                                                {} as Record<
                                                                    string,
                                                                    typeof activeTranslationValidationErrors
                                                                >
                                                            )

                                                        return Object.entries(errorsByLanguage).map(
                                                            ([lang, errors]) => (
                                                                <div key={lang} className="mb-2">
                                                                    <button
                                                                        type="button"
                                                                        onClick={(e) => {
                                                                            e.preventDefault()
                                                                            setEditingLanguage(
                                                                                lang === 'default' ? null : lang
                                                                            )
                                                                        }}
                                                                        className="font-semibold hover:underline cursor-pointer"
                                                                    >
                                                                        {lang === 'default'
                                                                            ? `Original (${getSurveyLanguageName(
                                                                                  getBaseLanguage(survey)
                                                                              )})`
                                                                            : COMMON_LANGUAGES.find(
                                                                                  (l) => l.value === lang
                                                                              )?.label || lang}
                                                                    </button>
                                                                    :
                                                                    <ul className="ml-4 list-disc">
                                                                        {errors.map((error, idx) => (
                                                                            <li key={idx}>
                                                                                {error.questionIndex >= 0
                                                                                    ? `Question ${
                                                                                          error.questionIndex + 1
                                                                                      }`
                                                                                    : 'Survey'}{' '}
                                                                                - {formatFieldName(error.field)}:{' '}
                                                                                {error.error}
                                                                            </li>
                                                                        ))}
                                                                    </ul>
                                                                </div>
                                                            )
                                                        )
                                                    })()}
                                                </div>
                                            ),
                                            className: 'bg-warning-highlight',
                                        },
                                    ]}
                                />
                            )
                        } else if (activeEditingLanguage) {
                            const baseLanguageName = getSurveyLanguageName(getBaseLanguage(survey))
                            return (
                                <div className="px-4 py-2 mt-1 mb-1.5 bg-warning-highlight rounded border border-warning">
                                    <span className="text-sm">
                                        Editing translation for{' '}
                                        <strong>
                                            {COMMON_LANGUAGES.find((l) => l.value === activeEditingLanguage)?.label ||
                                                activeEditingLanguage}
                                        </strong>
                                        . Only user-facing text can be translated — structural fields stay in the{' '}
                                        <button
                                            type="button"
                                            onClick={() => setEditingLanguage(null)}
                                            className="font-semibold hover:underline cursor-pointer"
                                        >
                                            original ({baseLanguageName})
                                        </button>
                                        .
                                    </span>
                                </div>
                            )
                        }

                        return null
                    })()}
                </div>
                <div className="flex flex-col xl:grid xl:grid-cols-[1fr_400px] gap-x-4 h-full">
                    <div className="flex flex-col gap-2 flex-1 SurveyForm">
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
                                                        <div className="grid grid-cols-2 2xl:grid-cols-4 gap-4">
                                                            <PresentationTypeCard
                                                                active={value === SurveyType.Popover}
                                                                onClick={() => {
                                                                    onChange(SurveyType.Popover)
                                                                    if (survey.schedule === SurveySchedule.Always) {
                                                                        setSurveyValue('schedule', SurveySchedule.Once)
                                                                    }
                                                                }}
                                                                title={SURVEY_TYPE_LABEL_MAP[SurveyType.Popover]}
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
                                                                title={SURVEY_TYPE_LABEL_MAP[SurveyType.API]}
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
                                                                title={SURVEY_TYPE_LABEL_MAP[SurveyType.Widget]}
                                                                description="Set up a survey based on your own custom button or our prebuilt feedback tab"
                                                                value={SurveyType.Widget}
                                                            >
                                                                <button
                                                                    type="button"
                                                                    className="bg-black py-2 px-3 min-w-[40px] absolute right-3 -bottom-16 text-white opacity-30 rounded scale-[2]"
                                                                >
                                                                    Feedback
                                                                </button>
                                                            </PresentationTypeCard>
                                                            <PresentationTypeCard
                                                                active={value === SurveyType.ExternalSurvey}
                                                                onClick={() => onChange(SurveyType.ExternalSurvey)}
                                                                title={SURVEY_TYPE_LABEL_MAP[SurveyType.ExternalSurvey]}
                                                                description="Collect responses via an external link, hosted on PostHog. If you are already using surveys, make sure to upgrade posthog-js to at least v1.258.1."
                                                                value={SurveyType.ExternalSurvey}
                                                            >
                                                                <LemonTag type="warning">BETA</LemonTag>
                                                            </PresentationTypeCard>
                                                        </div>
                                                        {survey.type === SurveyType.Widget && (
                                                            <SurveyWidgetCustomization />
                                                        )}
                                                        {survey.type === SurveyType.ExternalSurvey && (
                                                            <>
                                                                <Tooltip title="Enable this to embed the survey in tools like Framer, Webflow, or other website builders that use iframes.">
                                                                    <LemonSwitch
                                                                        checked={!!survey.enable_iframe_embedding}
                                                                        onChange={(checked) =>
                                                                            setSurveyValue(
                                                                                'enable_iframe_embedding',
                                                                                checked
                                                                            )
                                                                        }
                                                                        label="Allow embedding in iframes"
                                                                        bordered
                                                                    />
                                                                </Tooltip>
                                                                <div className="font-semibold">
                                                                    How hosted surveys work:
                                                                </div>
                                                                <ul className="space-y-2 text-sm">
                                                                    <li>
                                                                        • The survey will be hosted by PostHog and you
                                                                        can share the URL with your customers
                                                                    </li>
                                                                    <li>
                                                                        • To identify respondents, add the{' '}
                                                                        <code className="bg-surface-tertiary px-1 rounded">
                                                                            distinct_id
                                                                        </code>{' '}
                                                                        query parameter to the URL. Here's an example:
                                                                        {'\n'}
                                                                        <Link
                                                                            to={`https://us.posthog.com/external_surveys/01984280-fc8a-0000-28a5-01078e2d553f?distinct_id=${
                                                                                user?.email ?? 'john@acme.co'
                                                                            }`}
                                                                            target="_blank"
                                                                        >{`https://us.posthog.com/external_surveys/01984280-fc8a-0000-28a5-01078e2d553f?distinct_id=${
                                                                            user?.email ?? 'john@acme.co'
                                                                        }`}</Link>
                                                                    </li>
                                                                    <li>
                                                                        • Check more details about identifying
                                                                        respondents in the{' '}
                                                                        <Link
                                                                            to="https://posthog.com/docs/surveys/creating-surveys#identifying-respondents-on-hosted-surveys"
                                                                            target="_blank"
                                                                        >
                                                                            documentation
                                                                        </Link>
                                                                    </li>
                                                                </ul>
                                                            </>
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
                                            {surveyTranslationsEnabled ? (
                                                <div className="mb-4">
                                                    <SurveyTranslations />
                                                </div>
                                            ) : null}
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
                                                        activeKey={
                                                            selectedPageIndex === null ? undefined : selectedPageIndex
                                                        }
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
                                                                            translationValidationErrors={
                                                                                activeTranslationValidationErrors
                                                                            }
                                                                            translationErrorsByQuestion={
                                                                                translationErrorsByQuestion
                                                                            }
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
                                                                                  <div className="flex items-center gap-1">
                                                                                      {(() => {
                                                                                          const confirmationErrors =
                                                                                              getConfirmationMessageErrors()
                                                                                          return confirmationErrors >
                                                                                              0 ? (
                                                                                              <Tooltip
                                                                                                  title={`${confirmationErrors} translation validation issue${
                                                                                                      confirmationErrors >
                                                                                                      1
                                                                                                          ? 's'
                                                                                                          : ''
                                                                                                  }`}
                                                                                              >
                                                                                                  <IconWarning className="text-warning" />
                                                                                              </Tooltip>
                                                                                          ) : null
                                                                                      })()}
                                                                                      <LemonButton
                                                                                          icon={<IconTrash />}
                                                                                          data-attr="delete-survey-confirmation"
                                                                                          size="xsmall"
                                                                                          onClick={(e) => {
                                                                                              const deleteConfirmationMessage =
                                                                                                  (): void => {
                                                                                                      e.stopPropagation()
                                                                                                      setSelectedPageIndex(
                                                                                                          survey
                                                                                                              .questions
                                                                                                              .length -
                                                                                                              1
                                                                                                      )
                                                                                                      setSurveyValue(
                                                                                                          'appearance',
                                                                                                          {
                                                                                                              ...survey.appearance,
                                                                                                              displayThankYouMessage: false,
                                                                                                          }
                                                                                                      )
                                                                                                  }

                                                                                              if (hasBranchingLogic) {
                                                                                                  LemonDialog.open({
                                                                                                      title: 'Your survey has active branching logic',
                                                                                                      description: (
                                                                                                          <p className="py-2">
                                                                                                              Deleting
                                                                                                              the
                                                                                                              confirmation
                                                                                                              message
                                                                                                              will
                                                                                                              remove
                                                                                                              your
                                                                                                              branching
                                                                                                              logic. Are
                                                                                                              you sure
                                                                                                              you want
                                                                                                              to
                                                                                                              continue?
                                                                                                          </p>
                                                                                                      ),
                                                                                                      primaryButton: {
                                                                                                          children:
                                                                                                              'Continue',
                                                                                                          status: 'danger',
                                                                                                          onClick:
                                                                                                              () => {
                                                                                                                  deleteBranchingLogic()
                                                                                                                  deleteConfirmationMessage()
                                                                                                              },
                                                                                                      },
                                                                                                      secondaryButton: {
                                                                                                          children:
                                                                                                              'Cancel',
                                                                                                      },
                                                                                                  })
                                                                                              } else {
                                                                                                  deleteConfirmationMessage()
                                                                                              }
                                                                                          }}
                                                                                          tooltipPlacement="top-end"
                                                                                      />
                                                                                  </div>
                                                                              </div>
                                                                          ),
                                                                          content: (
                                                                              <>
                                                                                  <LemonField.Pure
                                                                                      label={getFieldLabel(
                                                                                          'Thank you header',
                                                                                          'thankYouMessageHeader'
                                                                                      )}
                                                                                  >
                                                                                      {(() => {
                                                                                          const fieldError =
                                                                                              getFieldError(
                                                                                                  'thankYouMessageHeader'
                                                                                              )
                                                                                          return (
                                                                                              <Tooltip
                                                                                                  title={
                                                                                                      fieldError?.error ||
                                                                                                      ''
                                                                                                  }
                                                                                                  placement="top"
                                                                                              >
                                                                                                  <LemonInput
                                                                                                      value={
                                                                                                          activeEditingLanguage
                                                                                                              ? (survey
                                                                                                                    .translations?.[
                                                                                                                    activeEditingLanguage
                                                                                                                ]
                                                                                                                    ?.thankYouMessageHeader ??
                                                                                                                '')
                                                                                                              : (survey
                                                                                                                    .appearance
                                                                                                                    .thankYouMessageHeader ??
                                                                                                                '')
                                                                                                      }
                                                                                                      onChange={(
                                                                                                          val
                                                                                                      ) => {
                                                                                                          if (
                                                                                                              activeEditingLanguage
                                                                                                          ) {
                                                                                                              clearAiGeneratedTranslationField(
                                                                                                                  `translations.${activeEditingLanguage}.thankYouMessageHeader`
                                                                                                              )
                                                                                                              setSurveyValue(
                                                                                                                  'translations',
                                                                                                                  {
                                                                                                                      ...surveyTranslations,
                                                                                                                      [activeEditingLanguage]:
                                                                                                                          {
                                                                                                                              ...survey
                                                                                                                                  .translations?.[
                                                                                                                                  activeEditingLanguage
                                                                                                                              ],
                                                                                                                              thankYouMessageHeader:
                                                                                                                                  val,
                                                                                                                          },
                                                                                                                  }
                                                                                                              )
                                                                                                          } else {
                                                                                                              setSurveyValue(
                                                                                                                  'appearance',
                                                                                                                  {
                                                                                                                      ...survey.appearance,
                                                                                                                      thankYouMessageHeader:
                                                                                                                          val,
                                                                                                                  }
                                                                                                              )
                                                                                                          }
                                                                                                      }}
                                                                                                      placeholder={
                                                                                                          activeEditingLanguage
                                                                                                              ? survey
                                                                                                                    .appearance
                                                                                                                    .thankYouMessageHeader
                                                                                                              : 'ex: Thank you for your feedback!'
                                                                                                      }
                                                                                                      className={getFieldErrorClass(
                                                                                                          'thankYouMessageHeader'
                                                                                                      )}
                                                                                                  />
                                                                                              </Tooltip>
                                                                                          )
                                                                                      })()}
                                                                                  </LemonField.Pure>
                                                                                  <LemonField.Pure
                                                                                      label={getFieldLabel(
                                                                                          'Thank you description',
                                                                                          'thankYouMessageDescription'
                                                                                      )}
                                                                                      className="mt-3"
                                                                                  >
                                                                                      {(() => {
                                                                                          const fieldError =
                                                                                              getFieldError(
                                                                                                  'thankYouMessageDescription'
                                                                                              )
                                                                                          return (
                                                                                              <Tooltip
                                                                                                  title={
                                                                                                      fieldError?.error ||
                                                                                                      ''
                                                                                                  }
                                                                                                  placement="top"
                                                                                              >
                                                                                                  <HTMLEditor
                                                                                                      value={
                                                                                                          activeEditingLanguage
                                                                                                              ? (survey
                                                                                                                    .translations?.[
                                                                                                                    activeEditingLanguage
                                                                                                                ]
                                                                                                                    ?.thankYouMessageDescription ??
                                                                                                                '')
                                                                                                              : (survey
                                                                                                                    .appearance
                                                                                                                    .thankYouMessageDescription ??
                                                                                                                '')
                                                                                                      }
                                                                                                      onChange={(
                                                                                                          val
                                                                                                      ) => {
                                                                                                          if (
                                                                                                              activeEditingLanguage
                                                                                                          ) {
                                                                                                              clearAiGeneratedTranslationField(
                                                                                                                  `translations.${activeEditingLanguage}.thankYouMessageDescription`
                                                                                                              )
                                                                                                              setSurveyValue(
                                                                                                                  'translations',
                                                                                                                  {
                                                                                                                      ...surveyTranslations,
                                                                                                                      [activeEditingLanguage]:
                                                                                                                          {
                                                                                                                              ...survey
                                                                                                                                  .translations?.[
                                                                                                                                  activeEditingLanguage
                                                                                                                              ],
                                                                                                                              thankYouMessageDescription:
                                                                                                                                  val,
                                                                                                                          },
                                                                                                                  }
                                                                                                              )
                                                                                                          } else {
                                                                                                              setSurveyValue(
                                                                                                                  'appearance',
                                                                                                                  {
                                                                                                                      ...survey.appearance,
                                                                                                                      thankYouMessageDescription:
                                                                                                                          val,
                                                                                                                      thankYouMessageDescriptionContentType,
                                                                                                                  }
                                                                                                              )
                                                                                                          }
                                                                                                      }}
                                                                                                      onTabChange={(
                                                                                                          key
                                                                                                      ) => {
                                                                                                          if (
                                                                                                              activeEditingLanguage
                                                                                                          ) {
                                                                                                              return
                                                                                                          }
                                                                                                          const updatedAppearance =
                                                                                                              {
                                                                                                                  ...survey.appearance,
                                                                                                                  thankYouMessageDescriptionContentType:
                                                                                                                      key ===
                                                                                                                      'html'
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
                                                                                                      textPlaceholder={
                                                                                                          activeEditingLanguage
                                                                                                              ? survey
                                                                                                                    .appearance
                                                                                                                    .thankYouMessageDescription
                                                                                                              : 'ex: We really appreciate it.'
                                                                                                      }
                                                                                                      disableTabSwitching={
                                                                                                          !!activeEditingLanguage
                                                                                                      }
                                                                                                      className={getFieldErrorClass(
                                                                                                          'thankYouMessageDescription'
                                                                                                      )}
                                                                                                  />
                                                                                              </Tooltip>
                                                                                          )
                                                                                      })()}
                                                                                  </LemonField.Pure>
                                                                                  <LemonField.Pure
                                                                                      className="mt-2"
                                                                                      label={getFieldLabel(
                                                                                          'Button text',
                                                                                          'thankYouMessageCloseButtonText'
                                                                                      )}
                                                                                  >
                                                                                      {(() => {
                                                                                          const fieldError =
                                                                                              getFieldError(
                                                                                                  'thankYouMessageCloseButtonText'
                                                                                              )
                                                                                          return (
                                                                                              <Tooltip
                                                                                                  title={
                                                                                                      fieldError?.error ||
                                                                                                      ''
                                                                                                  }
                                                                                                  placement="top"
                                                                                              >
                                                                                                  <LemonInput
                                                                                                      value={
                                                                                                          activeEditingLanguage
                                                                                                              ? (survey
                                                                                                                    .translations?.[
                                                                                                                    activeEditingLanguage
                                                                                                                ]
                                                                                                                    ?.thankYouMessageCloseButtonText ??
                                                                                                                '')
                                                                                                              : (survey
                                                                                                                    .appearance
                                                                                                                    .thankYouMessageCloseButtonText ??
                                                                                                                '')
                                                                                                      }
                                                                                                      onChange={(
                                                                                                          val
                                                                                                      ) => {
                                                                                                          if (
                                                                                                              activeEditingLanguage
                                                                                                          ) {
                                                                                                              clearAiGeneratedTranslationField(
                                                                                                                  `translations.${activeEditingLanguage}.thankYouMessageCloseButtonText`
                                                                                                              )
                                                                                                              setSurveyValue(
                                                                                                                  'translations',
                                                                                                                  {
                                                                                                                      ...surveyTranslations,
                                                                                                                      [activeEditingLanguage]:
                                                                                                                          {
                                                                                                                              ...survey
                                                                                                                                  .translations?.[
                                                                                                                                  activeEditingLanguage
                                                                                                                              ],
                                                                                                                              thankYouMessageCloseButtonText:
                                                                                                                                  val,
                                                                                                                          },
                                                                                                                  }
                                                                                                              )
                                                                                                          } else {
                                                                                                              setSurveyValue(
                                                                                                                  'appearance',
                                                                                                                  {
                                                                                                                      ...survey.appearance,
                                                                                                                      thankYouMessageCloseButtonText:
                                                                                                                          val,
                                                                                                                  }
                                                                                                              )
                                                                                                          }
                                                                                                      }}
                                                                                                      placeholder={
                                                                                                          activeEditingLanguage
                                                                                                              ? survey
                                                                                                                    .appearance
                                                                                                                    .thankYouMessageCloseButtonText
                                                                                                              : 'example: Close'
                                                                                                      }
                                                                                                      className={getFieldErrorClass(
                                                                                                          'thankYouMessageCloseButtonText'
                                                                                                      )}
                                                                                                  />
                                                                                              </Tooltip>
                                                                                          )
                                                                                      })()}
                                                                                  </LemonField.Pure>
                                                                                  <LemonField.Pure className="mt-2">
                                                                                      <Tooltip
                                                                                          title={
                                                                                              activeEditingLanguage
                                                                                                  ? 'Auto disappear can only be changed in the original language'
                                                                                                  : undefined
                                                                                          }
                                                                                      >
                                                                                          <LemonCheckbox
                                                                                              checked={
                                                                                                  !!survey.appearance
                                                                                                      .autoDisappear
                                                                                              }
                                                                                              label="Auto disappear"
                                                                                              disabled={
                                                                                                  activeEditingLanguage !==
                                                                                                  null
                                                                                              }
                                                                                              onChange={(checked) =>
                                                                                                  setSurveyValue(
                                                                                                      'appearance',
                                                                                                      {
                                                                                                          ...survey.appearance,
                                                                                                          autoDisappear:
                                                                                                              checked,
                                                                                                      }
                                                                                                  )
                                                                                              }
                                                                                          />
                                                                                      </Tooltip>
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
                                                        disabled={activeEditingLanguage !== null}
                                                        disabledReason={
                                                            activeEditingLanguage
                                                                ? 'Cannot add questions while editing a translation'
                                                                : undefined
                                                        }
                                                        onClick={() => {
                                                            const newQuestion = {
                                                                ...defaultSurveyFieldValues.open.questions[0],
                                                            } as any

                                                            // Initialize translations for all existing languages
                                                            const existingLanguages = Object.keys(
                                                                survey.translations || {}
                                                            )
                                                            if (existingLanguages.length > 0) {
                                                                newQuestion.translations = {}
                                                                existingLanguages.forEach((lang) => {
                                                                    newQuestion.translations[lang] = {
                                                                        question: newQuestion.question || '',
                                                                        description: newQuestion.description || '',
                                                                        buttonText: newQuestion.buttonText || '',
                                                                    }
                                                                })
                                                            }

                                                            setSurveyValue('questions', [
                                                                ...survey.questions,
                                                                newQuestion,
                                                            ])
                                                            setSelectedPageIndex(survey.questions.length)
                                                        }}
                                                    >
                                                        Add question
                                                    </LemonButton>
                                                    {hasBranchingLogic && (
                                                        <LemonButton
                                                            data-attr="preview-survey-branching"
                                                            type="secondary"
                                                            className="w-max"
                                                            icon={<IconGitBranch />}
                                                            onClick={() => setShowFlowModal(true)}
                                                        >
                                                            Preview branching flow
                                                        </LemonButton>
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
                                ...(survey.type !== SurveyType.ExternalSurvey
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
                                                              onTranslationsChange={(translations) =>
                                                                  setSurveyValue('translations', translations)
                                                              }
                                                              hasRatingButtons={survey.questions.some(
                                                                  (question) =>
                                                                      question.type === SurveyQuestionType.Rating
                                                              )}
                                                              hasPlaceholderText={survey.questions.some(
                                                                  (question) =>
                                                                      question.type === SurveyQuestionType.Open
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
                                                                  if (
                                                                      'surveyPopupDelaySeconds' in appearance &&
                                                                      !appearance.surveyPopupDelaySeconds &&
                                                                      survey.conditions?.cancelEvents?.values?.length
                                                                  ) {
                                                                      setSurveyValue('conditions', {
                                                                          ...survey.conditions,
                                                                          cancelEvents: undefined,
                                                                      })
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
                                ...(survey.type !== SurveyType.ExternalSurvey
                                    ? [
                                          {
                                              key: SurveyEditSection.DisplayConditions,
                                              header: 'Display conditions',
                                              dataAttr: 'survey-display-conditions',
                                              content: (
                                                  <LemonField.Pure>
                                                      <LemonRadio
                                                          value={hasTargetingSet ? 'matching' : 'all'}
                                                          onChange={(value) => {
                                                              if (value === 'all') {
                                                                  resetTargeting()
                                                              } else {
                                                                  // Proxy value so the conditions block renders and the
                                                                  // user can start editing or return to "all users".
                                                                  setSurveyValue('conditions', { url: '' })
                                                              }
                                                          }}
                                                          options={[
                                                              {
                                                                  value: 'all',
                                                                  label: 'All users',
                                                                  description: 'Show this survey to everyone',
                                                              },
                                                              {
                                                                  value: 'matching',
                                                                  label: 'Only users who match conditions',
                                                                  description:
                                                                      'Show this survey only when every condition below is met',
                                                                  'data-attr': 'survey-display-conditions-select-users',
                                                              },
                                                          ]}
                                                          data-attr="survey-display-conditions-select"
                                                      />
                                                      {hasTargetingSet && (
                                                          <>
                                                              <h3 className="text-xs font-semibold text-secondary uppercase tracking-wider mt-3 mb-0">
                                                                  Targeting
                                                              </h3>
                                                              <LemonField
                                                                  name="linked_flag_id"
                                                                  label="Feature flag targeting"
                                                                  help="Linking a flag also enables the survey for everyone the flag is on for."
                                                              >
                                                                  {({ value, onChange }) => (
                                                                      <div
                                                                          className="flex items-center gap-2"
                                                                          data-attr="survey-display-conditions-linked-flag"
                                                                      >
                                                                          <FlagSelector
                                                                              value={value}
                                                                              onChange={(id, _key, flag) => {
                                                                                  onChange(id)
                                                                                  if (
                                                                                      survey.linked_flag_id &&
                                                                                      !survey.linked_flag
                                                                                  ) {
                                                                                      api.featureFlags
                                                                                          .get(survey.linked_flag_id)
                                                                                          .then((flag) => {
                                                                                              setSurveyValue(
                                                                                                  'linked_flag',
                                                                                                  flag
                                                                                              )
                                                                                          })
                                                                                          .catch(() => {
                                                                                              // If flag doesn't exist anymore, clear the linked_flag_id
                                                                                              setSurveyValue(
                                                                                                  'linked_flag_id',
                                                                                                  null
                                                                                              )
                                                                                              // Reset variant selection when flag changes
                                                                                              const {
                                                                                                  linkedFlagVariant,
                                                                                                  ...conditions
                                                                                              } =
                                                                                                  survey.conditions ||
                                                                                                  {}
                                                                                              setSurveyValue(
                                                                                                  'conditions',
                                                                                                  {
                                                                                                      ...conditions,
                                                                                                  }
                                                                                              )
                                                                                          })
                                                                                  } else {
                                                                                      setSurveyValue(
                                                                                          'linked_flag',
                                                                                          flag
                                                                                      )
                                                                                      // Reset variant selection when flag changes
                                                                                      const {
                                                                                          linkedFlagVariant,
                                                                                          ...conditions
                                                                                      } = survey.conditions || {}
                                                                                      setSurveyValue('conditions', {
                                                                                          ...conditions,
                                                                                      })
                                                                                  }
                                                                              }}
                                                                          />
                                                                          {value && (
                                                                              <LemonButton
                                                                                  type="tertiary"
                                                                                  size="small"
                                                                                  icon={<IconTrash />}
                                                                                  onClick={() => {
                                                                                      onChange(null)
                                                                                      setSurveyValue(
                                                                                          'linked_flag',
                                                                                          null
                                                                                      )
                                                                                      const {
                                                                                          linkedFlagVariant,
                                                                                          ...conditions
                                                                                      } = survey.conditions || {}
                                                                                      setSurveyValue('conditions', {
                                                                                          ...conditions,
                                                                                      })
                                                                                  }}
                                                                              >
                                                                                  Clear
                                                                              </LemonButton>
                                                                          )}
                                                                      </div>
                                                                  )}
                                                              </LemonField>
                                                              {survey.linked_flag?.filters.multivariate && (
                                                                  <LemonField.Pure
                                                                      label="Link to a specific flag variant"
                                                                      info="Choose which variant of the feature flag to link to this survey.
                                                              Requires posthog-js v1.259.0 or greater or posthog-react-native v4.4.0 or greater"
                                                                  >
                                                                      <div className="flex flex-col gap-2">
                                                                          <LemonSegmentedButton
                                                                              className="min-w-1/3"
                                                                              value={
                                                                                  survey.conditions
                                                                                      ?.linkedFlagVariant ?? ANY_VARIANT
                                                                              }
                                                                              options={variantOptions(
                                                                                  survey.linked_flag?.filters
                                                                                      .multivariate || undefined
                                                                              )}
                                                                              onChange={(variant) => {
                                                                                  setSurveyValue('conditions', {
                                                                                      ...survey.conditions,
                                                                                      linkedFlagVariant:
                                                                                          variant === ANY_VARIANT
                                                                                              ? null
                                                                                              : variant,
                                                                                  })
                                                                              }}
                                                                          />
                                                                          <p className="text-sm text-secondary">
                                                                              This is a multi-variant flag. You can link
                                                                              to "any" variant of the flag, and the
                                                                              survey will be shown whenever the flag is
                                                                              enabled for a user. Alternatively, you can
                                                                              link to a specific variant of the flag,
                                                                              and the survey will only be shown when the
                                                                              user has that specific variant enabled.
                                                                          </p>
                                                                      </div>
                                                                  </LemonField.Pure>
                                                              )}
                                                              <LemonField name="conditions">
                                                                  {({ value, onChange }) => (
                                                                      <>
                                                                          <LemonField.Pure
                                                                              label="URL targeting"
                                                                              error={urlMatchTypeValidationError}
                                                                              help="Regex and exact match need posthog-js 1.82+."
                                                                          >
                                                                              <div className="flex flex-row gap-2 items-center">
                                                                                  <LemonSelect
                                                                                      className="w-40 shrink-0"
                                                                                      value={
                                                                                          value?.urlMatchType ||
                                                                                          SurveyMatchType.Contains
                                                                                      }
                                                                                      onChange={(matchTypeVal) => {
                                                                                          onChange({
                                                                                              ...value,
                                                                                              urlMatchType:
                                                                                                  matchTypeVal,
                                                                                          })
                                                                                      }}
                                                                                      data-attr="survey-url-matching-type"
                                                                                      options={(
                                                                                          Object.keys(
                                                                                              SurveyMatchTypeLabels
                                                                                          ) as Array<
                                                                                              ValueOf<
                                                                                                  typeof SurveyMatchType
                                                                                              >
                                                                                          >
                                                                                      ).map((key) => ({
                                                                                          label: SurveyMatchTypeLabels[
                                                                                              key
                                                                                          ],
                                                                                          value: key,
                                                                                      }))}
                                                                                  />
                                                                                  <LemonInput
                                                                                      value={value?.url}
                                                                                      onChange={(urlVal) =>
                                                                                          onChange({
                                                                                              ...value,
                                                                                              url: urlVal,
                                                                                          })
                                                                                      }
                                                                                      placeholder="ex: https://app.posthog.com"
                                                                                      fullWidth
                                                                                  />
                                                                              </div>
                                                                          </LemonField.Pure>
                                                                          <LemonField.Pure
                                                                              label="Device types"
                                                                              error={
                                                                                  deviceTypesMatchTypeValidationError
                                                                              }
                                                                              help={
                                                                                  <>
                                                                                      <Link
                                                                                          to="https://posthog.com/docs/surveys/creating-surveys#display-conditions"
                                                                                          target="_blank"
                                                                                      >
                                                                                          See accepted values
                                                                                      </Link>
                                                                                      . Needs posthog-js 1.214+.
                                                                                  </>
                                                                              }
                                                                          >
                                                                              <div className="flex flex-row gap-2 items-center">
                                                                                  <LemonSelect
                                                                                      className="w-40 shrink-0"
                                                                                      value={
                                                                                          value?.deviceTypesMatchType ||
                                                                                          SurveyMatchType.Contains
                                                                                      }
                                                                                      onChange={(matchTypeVal) => {
                                                                                          onChange({
                                                                                              ...value,
                                                                                              deviceTypesMatchType:
                                                                                                  matchTypeVal,
                                                                                          })
                                                                                      }}
                                                                                      data-attr="survey-device-types-matching-type"
                                                                                      options={(
                                                                                          Object.keys(
                                                                                              SurveyMatchTypeLabels
                                                                                          ) as Array<
                                                                                              ValueOf<
                                                                                                  typeof SurveyMatchType
                                                                                              >
                                                                                          >
                                                                                      ).map((key) => ({
                                                                                          label: SurveyMatchTypeLabels[
                                                                                              key
                                                                                          ],
                                                                                          value: key,
                                                                                      }))}
                                                                                  />
                                                                                  {[
                                                                                      SurveyMatchType.Regex,
                                                                                      SurveyMatchType.NotRegex,
                                                                                  ].includes(
                                                                                      value?.deviceTypesMatchType ||
                                                                                          SurveyMatchType.Contains
                                                                                  ) ? (
                                                                                      <LemonInput
                                                                                          value={value?.deviceTypes?.join(
                                                                                              '|'
                                                                                          )}
                                                                                          onChange={(deviceTypesVal) =>
                                                                                              onChange({
                                                                                                  ...value,
                                                                                                  deviceTypes: [
                                                                                                      deviceTypesVal,
                                                                                                  ],
                                                                                              })
                                                                                          }
                                                                                          // regex placeholder for device type
                                                                                          className="flex-1"
                                                                                          placeholder="ex: Desktop|Mobile"
                                                                                      />
                                                                                  ) : (
                                                                                      <div className="flex-1 min-w-0">
                                                                                          <PropertyValue
                                                                                              propertyKey={getPropertyKey(
                                                                                                  'Device Type',
                                                                                                  TaxonomicFilterGroupType.EventProperties
                                                                                              )}
                                                                                              type={
                                                                                                  PropertyFilterType.Event
                                                                                              }
                                                                                              onSet={(
                                                                                                  deviceTypes:
                                                                                                      | string
                                                                                                      | string[]
                                                                                              ) => {
                                                                                                  onChange({
                                                                                                      ...value,
                                                                                                      deviceTypes:
                                                                                                          Array.isArray(
                                                                                                              deviceTypes
                                                                                                          )
                                                                                                              ? deviceTypes
                                                                                                              : [
                                                                                                                    deviceTypes,
                                                                                                                ],
                                                                                                  })
                                                                                              }}
                                                                                              operator={
                                                                                                  PropertyOperator.Exact
                                                                                              }
                                                                                              value={value?.deviceTypes}
                                                                                              inputClassName="w-full"
                                                                                          />
                                                                                      </div>
                                                                                  )}
                                                                              </div>
                                                                          </LemonField.Pure>
                                                                          <LemonField.Pure label="CSS selector matches">
                                                                              <LemonInput
                                                                                  value={value?.selector}
                                                                                  onChange={(selectorVal) =>
                                                                                      onChange({
                                                                                          ...value,
                                                                                          selector: selectorVal,
                                                                                      })
                                                                                  }
                                                                                  placeholder="ex: .className or #id"
                                                                              />
                                                                          </LemonField.Pure>
                                                                          <LemonField.Pure
                                                                              label="Survey wait period"
                                                                              help="Reliable only for identified users in the same browser session — incognito, browser switches, and logout/login may still see the survey again."
                                                                          >
                                                                              <div className="flex flex-wrap gap-2 items-center text-sm">
                                                                                  <LemonCheckbox
                                                                                      checked={
                                                                                          !!value?.seenSurveyWaitPeriodInDays
                                                                                      }
                                                                                      onChange={(checked) => {
                                                                                          onChange({
                                                                                              ...value,
                                                                                              seenSurveyWaitPeriodInDays:
                                                                                                  checked
                                                                                                      ? value?.seenSurveyWaitPeriodInDays ||
                                                                                                        30
                                                                                                      : null,
                                                                                          })
                                                                                      }}
                                                                                      label="Don't show this survey if another one was shown to the user in the last"
                                                                                  />
                                                                                  <div className="flex items-center gap-2">
                                                                                      <LemonInput
                                                                                          type="number"
                                                                                          size="xsmall"
                                                                                          min={1}
                                                                                          value={
                                                                                              value?.seenSurveyWaitPeriodInDays ??
                                                                                              undefined
                                                                                          }
                                                                                          onChange={(val) =>
                                                                                              onChange({
                                                                                                  ...value,
                                                                                                  seenSurveyWaitPeriodInDays:
                                                                                                      val && val > 0
                                                                                                          ? val
                                                                                                          : null,
                                                                                              })
                                                                                          }
                                                                                          className="w-16 tabular-nums"
                                                                                          id="survey-wait-period-input"
                                                                                      />
                                                                                      <span className="text-secondary">
                                                                                          days.
                                                                                      </span>
                                                                                  </div>
                                                                              </div>
                                                                          </LemonField.Pure>
                                                                      </>
                                                                  )}
                                                              </LemonField>
                                                              <LemonField.Pure label="Audience filters">
                                                                  <BindLogic
                                                                      logic={featureFlagLogic}
                                                                      props={{
                                                                          id: survey.targeting_flag?.id || 'new',
                                                                      }}
                                                                  >
                                                                      {!targetingFlagFilters && (
                                                                          <LemonButton
                                                                              type="secondary"
                                                                              className="w-max"
                                                                              onClick={() => {
                                                                                  setSurveyValue(
                                                                                      'targeting_flag_filters',
                                                                                      {
                                                                                          groups: [
                                                                                              {
                                                                                                  properties: [],
                                                                                                  rollout_percentage: 100,
                                                                                                  variant: null,
                                                                                              },
                                                                                          ],
                                                                                          multivariate: null,
                                                                                          payloads: {},
                                                                                      }
                                                                                  )
                                                                                  setSurveyValue(
                                                                                      'remove_targeting_flag',
                                                                                      false
                                                                                  )
                                                                              }}
                                                                          >
                                                                              Add property targeting
                                                                          </LemonButton>
                                                                      )}
                                                                      {targetingFlagFilters && (
                                                                          <>
                                                                              <div className="mt-2">
                                                                                  <FeatureFlagReleaseConditions
                                                                                      id={
                                                                                          String(
                                                                                              survey.targeting_flag?.id
                                                                                          ) || 'new'
                                                                                      }
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
                                                              <h3 className="text-xs font-semibold text-secondary uppercase tracking-wider mt-4 mb-0">
                                                                  Triggers
                                                              </h3>
                                                              {featureFlags[FEATURE_FLAGS.SURVEYS_ACTIONS] ? (
                                                                  <LemonField.Pure label="Activation triggers">
                                                                      <div className="space-y-4">
                                                                          <SurveyEventTrigger />
                                                                          <div className="flex items-center gap-2">
                                                                              <div className="flex-1 border-t border-dashed" />
                                                                              <span className="text-xs font-semibold text-muted uppercase">
                                                                                  or
                                                                              </span>
                                                                              <div className="flex-1 border-t border-dashed" />
                                                                          </div>
                                                                          <SurveyActionTrigger />
                                                                      </div>
                                                                  </LemonField.Pure>
                                                              ) : (
                                                                  <SurveyEventTrigger />
                                                              )}
                                                              {!!survey.appearance?.surveyPopupDelaySeconds && (
                                                                  <SurveyCancelEventTrigger />
                                                              )}
                                                          </>
                                                      )}
                                                  </LemonField.Pure>
                                              ),
                                          },
                                      ]
                                    : []),
                                {
                                    key: SurveyEditSection.CompletionConditions,
                                    header: 'Completion conditions',
                                    content: <SurveyCompletionConditions />,
                                },
                            ]}
                        />
                    </div>
                    <div className="h-full">
                        <div
                            className={`sticky ${
                                activeEditingLanguage || hasVisibleTranslationValidationErrors ? 'top-28' : 'top-16'
                            }`}
                        >
                            <SurveyFormAppearance
                                previewPageIndex={selectedPageIndex || 0}
                                survey={previewSurvey}
                                handleSetSelectedPageIndex={(pageIndex) => setSelectedPageIndex(pageIndex)}
                                isEditingSurvey={isEditingSurvey}
                            />
                        </div>
                    </div>
                </div>
            </div>
            <SurveyBranchingFlowModal survey={survey} isOpen={showFlowModal} onClose={() => setShowFlowModal(false)} />
        </SceneContent>
    )
}
