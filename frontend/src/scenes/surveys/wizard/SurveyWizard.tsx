import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SurveyQuestionBranchingType } from '~/types'

import { SdkVersionWarnings } from '../components/SdkVersionWarnings'
import { NewSurvey } from '../constants'
import { SurveyAppearancePreview } from '../SurveyAppearancePreview'
import { getEventPropertyFilterCount } from '../SurveyEventTrigger'
import { surveyLogic } from '../surveyLogic'
import { surveysLogic } from '../surveysLogic'
import { getSurveyWithTranslatedContent } from '../surveyTranslationUtils'
import { canUseSurveyWizard, doesSurveyHaveDisplayConditions, getSurveyAudienceSummaryValue } from '../utils'
import { MaxTip } from './MaxTip'
import { AppearanceStep } from './steps/AppearanceStep'
import { QuestionsStep } from './steps/QuestionsStep'
import { SuccessStep } from './steps/SuccessStep'
import { TemplateStep } from './steps/TemplateStep'
import { WhenStep } from './steps/WhenStep'
import { WhereStep } from './steps/WhereStep'
import { SurveyWizardLogicProps, surveyWizardLogic } from './surveyWizardLogic'
import { WizardStepper } from './WizardStepper'

export const scene: SceneExport<SurveyWizardLogicProps> = {
    component: SurveyWizardComponent,
    // Declaring the logic here keeps it (and its connected surveyLogic) mounted
    // across tab switches, so unsaved edits and the current step survive re-entry.
    logic: surveyWizardLogic,
    paramsToProps: ({ params: { id } }): SurveyWizardLogicProps => ({ id: id || 'new' }),
}

export function SurveyWizardComponent({ id }: SurveyWizardLogicProps): JSX.Element {
    return (
        <BindLogic logic={surveyWizardLogic} props={{ id }}>
            <BindLogic logic={surveyLogic} props={{ id }}>
                <SurveyWizard id={id} />
            </BindLogic>
        </BindLogic>
    )
}

function SurveyWizard({ id }: SurveyWizardLogicProps): JSX.Element {
    const {
        currentStep,
        createdSurvey,
        surveyLaunching,
        surveySaving,
        surveyLoading,
        stepValidationErrors,
        currentStepHasErrors,
    } = useValues(surveyWizardLogic)
    const isEditing = id !== 'new'
    const { nextStep, setStep, launchSurvey, saveDraft, updateSurvey } = useActions(surveyWizardLogic)

    const { survey, surveyWarnings } = useValues(surveyLogic)
    const { setSurveyValue, loadSurvey } = useActions(surveyLogic)

    const { setPreferredEditor } = useActions(surveysLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const surveyTranslationsEnabled = !!featureFlags[FEATURE_FLAGS.SURVEYS_TRANSLATIONS]

    // Redirect existing surveys that use wizard-unsupported fields to the full
    // editor. Brand-new surveys should always start on template selection,
    // regardless of the user's editor preference.
    // Hash-carrying deep links (#fromTemplate, #preserveLocalChanges) are
    // respected and bypass the redirect.
    useEffect(() => {
        if (window.location.hash) {
            return
        }
        if (isEditing && !surveyLoading && !canUseSurveyWizard(survey)) {
            router.actions.replace(`${urls.survey(id)}?edit=true`)
        }
    }, [isEditing, survey, surveyLoading, id])

    // register tool so edits from AI will always reload the survey data on-page
    useMaxTool({
        identifier: 'edit_survey',
        active: isEditing,
        callback: (toolOutput: { survey_id?: string; error?: string }) => {
            if (!toolOutput?.error && toolOutput?.survey_id === id) {
                loadSurvey()
            }
        },
    })

    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const [previewPageIndex, setPreviewPageIndex] = useState(0)
    const [guidedEditingLanguage, setGuidedEditingLanguage] = useState<string | null>(null)
    const activeEditingLanguage = surveyTranslationsEnabled ? guidedEditingLanguage : null

    const maxPreviewIndex = survey.appearance?.displayThankYouMessage
        ? survey.questions.length
        : survey.questions.length - 1

    useEffect(() => {
        setPreviewPageIndex((current) => (current > maxPreviewIndex ? Math.max(0, maxPreviewIndex) : current))
    }, [maxPreviewIndex])

    useEffect(() => {
        if (!surveyTranslationsEnabled && guidedEditingLanguage !== null) {
            setGuidedEditingLanguage(null)
        }
    }, [guidedEditingLanguage, surveyTranslationsEnabled])

    const handleCustomizeMore = (): void => {
        setPreferredEditor('full')
        const target = isEditing
            ? `${urls.survey(id)}?edit=true#preserveLocalChanges=true`
            : `${urls.survey(id)}#fromTemplate=true&preserveLocalChanges=true`
        router.actions.push(target)
    }

    // Show loading state while loading existing survey
    if (isEditing && surveyLoading) {
        return (
            <div className="min-h-full w-full shrink-0 bg-bg-light">
                <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
                    <LemonSkeleton className="h-10 w-full" />
                    <LemonSkeleton className="h-64 w-full" />
                </div>
            </div>
        )
    }

    // Template selection step - only for new surveys
    if (currentStep === 'template' && !isEditing) {
        return (
            <div className="min-h-full w-full shrink-0 bg-bg-light">
                <div className="mx-auto max-w-3xl space-y-5 p-8">
                    <div className="mb-6">
                        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.surveys()}>
                            Surveys
                        </LemonButton>
                    </div>
                    <TemplateStep handleCustomizeMore={handleCustomizeMore} />
                </div>
            </div>
        )
    }

    const previewSurvey: NewSurvey = {
        ...getSurveyWithTranslatedContent(survey, activeEditingLanguage),
        id,
    } as NewSurvey

    const getConditionsSummary = (): string[] => {
        const conditions = survey.conditions
        const summary: string[] = []

        if (conditions?.url) {
            summary.push(`URL ${conditions.urlMatchType === 'exact' ? 'is exactly' : 'contains'} "${conditions.url}"`)
        }

        if (conditions?.selector) {
            summary.push(`Element "${conditions.selector}" is present on page`)
        }

        if (conditions?.deviceTypes && conditions.deviceTypes.length > 0) {
            summary.push(`Device type is ${conditions.deviceTypes.join(' or ')}`)
        }

        if (conditions?.events?.values && conditions.events.values.length > 0) {
            const eventNames = conditions.events.values
                .map((event) => {
                    const propertyFilterCount = getEventPropertyFilterCount(event.propertyFilters)
                    return propertyFilterCount > 0
                        ? `${event.name} (${propertyFilterCount} property filter${propertyFilterCount !== 1 ? 's' : ''})`
                        : event.name
                })
                .join(', ')
            summary.push(`User performed event: ${eventNames}`)
        }

        if (survey.linked_flag?.key) {
            summary.push(
                survey.conditions?.linkedFlagVariant
                    ? `Feature flag: ${survey.linked_flag.key} (${survey.conditions.linkedFlagVariant} variant)`
                    : `Feature flag: ${survey.linked_flag.key}`
            )
        }

        const audienceSummary = getSurveyAudienceSummaryValue(survey)
        if (audienceSummary) {
            summary.push(`Audience: ${audienceSummary}`)
        }

        return summary
    }

    const showLaunchConfirmation = (onConfirm: () => void): void => {
        const hasConditions = doesSurveyHaveDisplayConditions(survey)
        const conditionsSummary = getConditionsSummary()
        const hasAudienceConditions = conditionsSummary.length > 0

        LemonDialog.open({
            title: 'Launch this survey?',
            content: (
                <div className="space-y-2">
                    <SdkVersionWarnings warnings={surveyWarnings} />
                    {hasConditions || hasAudienceConditions ? (
                        <>
                            <p className="text-secondary">
                                The survey will be shown to users who match these conditions:
                            </p>
                            <ul className="list-disc list-inside text-secondary">
                                {conditionsSummary.map((condition, i) => (
                                    <li key={i}>{condition}</li>
                                ))}
                            </ul>
                        </>
                    ) : (
                        <p className="text-secondary">The survey will immediately start displaying to all users.</p>
                    )}
                </div>
            ),
            primaryButton: {
                children: 'Launch',
                type: 'primary',
                onClick: onConfirm,
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
            },
        })
    }

    const handleLaunchClick = (): void => {
        if (!currentTeam?.surveys_opt_in) {
            LemonDialog.open({
                title: 'Enable surveys?',
                content: (
                    <p className="text-secondary">
                        Surveys are currently disabled for this project. Would you like to enable them and launch your
                        survey?
                    </p>
                ),
                primaryButton: {
                    children: 'Enable & continue',
                    type: 'primary',
                    onClick: () => {
                        updateCurrentTeam({ surveys_opt_in: true })
                        showLaunchConfirmation(launchSurvey)
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                    type: 'tertiary',
                },
            })
        } else {
            showLaunchConfirmation(launchSurvey)
        }
    }

    const handleSaveClick = (): void => {
        if (isEditing) {
            updateSurvey()
        } else {
            saveDraft()
        }
    }

    if (currentStep === 'success' && createdSurvey) {
        return (
            <div className="min-h-full w-full shrink-0 bg-bg-light">
                <div className="mx-auto max-w-2xl p-8">
                    <SuccessStep survey={createdSurvey} />
                </div>
            </div>
        )
    }

    // Navigation back button
    const backButton = isEditing ? (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.survey(id)}>
            Survey
        </LemonButton>
    ) : (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={() => setStep('template')}>
            Templates
        </LemonButton>
    )

    // Shared header for all main steps
    const header = (
        <div className="space-y-3">
            <div className="space-y-1">
                <div className="flex items-center justify-between">
                    {backButton}
                    <LemonButton type="secondary" size="small" onClick={handleCustomizeMore}>
                        Full editor
                    </LemonButton>
                </div>
                <div>
                    <label htmlFor="survey-name" className="text-xs font-medium text-muted">
                        Survey name
                    </label>
                    <EditableField
                        name="survey-name"
                        value={survey.name}
                        onSave={(value) => setSurveyValue('name', value)}
                        placeholder="Untitled survey"
                        saveOnBlur
                        clickToEdit
                        compactIcon
                        showEditIconOnHover
                        className="text-xl font-semibold"
                        editingIndication="underlined"
                    />
                </div>
            </div>
            <div className="flex justify-center">
                <WizardStepper currentStep={currentStep} onStepClick={setStep} stepErrors={stepValidationErrors} />
            </div>
        </div>
    )

    // Appearance step - full width with built-in preview
    if (currentStep === 'appearance') {
        return (
            <div className="min-h-full w-full shrink-0 bg-bg-light">
                <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
                    {header}
                    <AppearanceStep />

                    <div className="flex items-center justify-end pt-4 border-t border-border">
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="secondary"
                                loading={surveySaving}
                                disabled={surveyLaunching}
                                onClick={handleSaveClick}
                            >
                                {isEditing ? 'Save changes' : 'Save as draft'}
                            </LemonButton>
                            {!isEditing && (
                                <LemonButton
                                    type="primary"
                                    loading={surveyLaunching}
                                    disabled={surveySaving}
                                    disabledReason={currentStepHasErrors ? 'Fix errors before launching' : undefined}
                                    onClick={handleLaunchClick}
                                >
                                    Launch survey
                                </LemonButton>
                            )}
                        </div>
                    </div>

                    <MaxTip step={currentStep} />
                </div>
            </div>
        )
    }

    return (
        <div className="min-h-full w-full shrink-0 bg-bg-light">
            <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
                {header}

                <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
                    {/* Left: Form */}
                    <div className="space-y-5 lg:col-span-3">
                        <div>
                            {currentStep === 'questions' && (
                                <QuestionsStep
                                    editingLanguage={guidedEditingLanguage}
                                    setEditingLanguage={setGuidedEditingLanguage}
                                />
                            )}
                            {currentStep === 'where' && <WhereStep onOpenFullEditor={handleCustomizeMore} />}
                            {currentStep === 'when' && <WhenStep />}
                        </div>

                        <div className="flex items-center justify-end pt-4 border-t border-border">
                            <div className="flex items-center gap-2">
                                {currentStep === 'when' && (
                                    <LemonButton type="secondary" onClick={() => setStep('appearance')}>
                                        Customize appearance
                                    </LemonButton>
                                )}
                                <LemonButton
                                    type="secondary"
                                    loading={surveySaving}
                                    disabled={surveyLaunching}
                                    onClick={handleSaveClick}
                                >
                                    {isEditing ? 'Save changes' : 'Save as draft'}
                                </LemonButton>
                                {currentStep === 'when' ? (
                                    !isEditing && (
                                        <LemonButton
                                            type="primary"
                                            loading={surveyLaunching}
                                            disabled={surveySaving}
                                            disabledReason={
                                                currentStepHasErrors ? 'Fix errors before launching' : undefined
                                            }
                                            onClick={handleLaunchClick}
                                        >
                                            Launch survey
                                        </LemonButton>
                                    )
                                ) : (
                                    <LemonButton
                                        type="primary"
                                        onClick={nextStep}
                                        disabledReason={
                                            currentStepHasErrors ? 'Fix errors before continuing' : undefined
                                        }
                                    >
                                        Continue
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Right: Preview */}
                    <div className="lg:col-span-2 hidden lg:block">
                        <div className="sticky top-6">
                            <div
                                className={clsx(
                                    'flex items-center justify-center p-4 rounded-lg min-h-[360px] border border-border',
                                    isDarkModeOn ? 'bg-[#1d1f27]' : 'bg-white'
                                )}
                            >
                                <SurveyAppearancePreview
                                    survey={previewSurvey}
                                    previewPageIndex={previewPageIndex}
                                    onPreviewSubmit={(response) => {
                                        const next = getNextSurveyStep(previewSurvey, previewPageIndex, response)
                                        if (
                                            next === SurveyQuestionBranchingType.End &&
                                            !previewSurvey.appearance?.displayThankYouMessage
                                        ) {
                                            return
                                        }
                                        setPreviewPageIndex(
                                            next === SurveyQuestionBranchingType.End
                                                ? previewSurvey.questions.length
                                                : next
                                        )
                                    }}
                                />
                            </div>
                            {(previewSurvey.questions.length > 1 ||
                                previewSurvey.appearance?.displayThankYouMessage) && (
                                <div className="flex items-center justify-center gap-2 mt-2">
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconChevronLeft />}
                                        onClick={() => setPreviewPageIndex(Math.max(0, previewPageIndex - 1))}
                                        disabledReason={previewPageIndex === 0 ? 'First question' : undefined}
                                    />
                                    <span className="text-muted text-xs min-w-[60px] text-center">
                                        {`${previewPageIndex + 1} / ${maxPreviewIndex + 1}`}
                                    </span>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconChevronRight />}
                                        onClick={() =>
                                            setPreviewPageIndex(Math.min(maxPreviewIndex, previewPageIndex + 1))
                                        }
                                        disabledReason={previewPageIndex >= maxPreviewIndex ? 'Last screen' : undefined}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                <MaxTip step={currentStep} />
            </div>
        </div>
    )
}
