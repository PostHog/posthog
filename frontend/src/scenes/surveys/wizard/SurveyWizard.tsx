import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SurveyQuestionBranchingType } from '~/types'

import { SurveyAppearancePreview } from '../SurveyAppearancePreview'
import { NewSurvey } from '../constants'
import { surveyLogic } from '../surveyLogic'
import { MaxTip } from './MaxTip'
import { WizardStepper } from './WizardStepper'
import { AppearanceStep } from './steps/AppearanceStep'
import { QuestionsStep } from './steps/QuestionsStep'
import { SuccessStep } from './steps/SuccessStep'
import { TemplateStep } from './steps/TemplateStep'
import { WhenStep } from './steps/WhenStep'
import { WhereStep } from './steps/WhereStep'
import { SurveyWizardLogicProps, surveyWizardLogic } from './surveyWizardLogic'

export const scene: SceneExport<SurveyWizardLogicProps> = {
    component: SurveyWizardComponent,
    paramsToProps: ({ params: { id } }): SurveyWizardLogicProps => ({ id: id || 'new' }),
}

function SurveyWizardComponent({ id }: SurveyWizardLogicProps): JSX.Element {
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
        selectedTemplate,
        stepValidationErrors,
        currentStepHasErrors,
    } = useValues(surveyWizardLogic)
    const isEditing = id !== 'new'
    const { nextStep, setStep, launchSurvey, saveDraft, updateSurvey } = useActions(surveyWizardLogic)

    // Survey form state from surveyLogic
    const { survey } = useValues(surveyLogic)

    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    const [previewPageIndex, setPreviewPageIndex] = useState(0)

    // Reset preview index if it's out of bounds (e.g., when disabling thank you message)
    useEffect(() => {
        const maxIndex = survey.appearance?.displayThankYouMessage
            ? survey.questions.length
            : survey.questions.length - 1
        setPreviewPageIndex((current) => (current > maxIndex ? Math.max(0, maxIndex) : current))
    }, [survey.appearance?.displayThankYouMessage, survey.questions.length])

    // Show loading state while loading existing survey
    if (isEditing && surveyLoading) {
        return (
            <div className="min-h-screen bg-bg-light">
                <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
                    <LemonSkeleton className="h-10 w-full" />
                    <LemonSkeleton className="h-64 w-full" />
                </div>
            </div>
        )
    }

    // Template selection step - only for new surveys
    if (currentStep === 'template' && !isEditing) {
        return (
            <div className="min-h-screen bg-bg-light">
                <div className="max-w-3xl mx-auto p-8">
                    <div className="mb-6">
                        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.surveys()}>
                            Surveys
                        </LemonButton>
                    </div>
                    <TemplateStep />
                </div>
            </div>
        )
    }

    const previewSurvey: NewSurvey = {
        ...survey,
        id: id,
    } as NewSurvey

    const handleCustomizeMore = (): void => {
        // Survey state is already in surveyLogic, just navigate
        // For existing surveys use ?edit=true, for new surveys use #fromTemplate=true
        router.actions.push(urls.survey(id) + (isEditing ? '?edit=true' : '#fromTemplate=true'))
    }

    const handleLaunchClick = (): void => {
        const doLaunch = (): void => {
            launchSurvey()
        }

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
                    children: 'Enable & launch',
                    type: 'primary',
                    onClick: () => {
                        updateCurrentTeam({ surveys_opt_in: true })
                        doLaunch()
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                    type: 'tertiary',
                },
            })
        } else {
            doLaunch()
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
            <div className="min-h-screen bg-bg-light">
                <div className="max-w-2xl mx-auto p-8">
                    <SuccessStep survey={createdSurvey} />
                </div>
            </div>
        )
    }

    // Back button destination with template indicator
    const backButton = isEditing ? (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.survey(id)}>
            Survey
        </LemonButton>
    ) : (
        <div className="flex items-center gap-2">
            <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={() => setStep('template')}>
                Templates
            </LemonButton>
            {selectedTemplate && <span className="text-muted text-sm">· {selectedTemplate.templateType}</span>}
        </div>
    )

    // Shared header for all main steps
    const header = (
        <div className="space-y-4">
            {backButton}
            <div className="flex justify-center">
                <WizardStepper currentStep={currentStep} onStepClick={setStep} stepErrors={stepValidationErrors} />
            </div>
        </div>
    )

    // Appearance step - full width with built-in preview
    if (currentStep === 'appearance') {
        return (
            <div className="min-h-screen bg-bg-light">
                <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
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
        <div className="min-h-screen bg-bg-light">
            <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
                {header}

                <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
                    {/* Left: Form */}
                    <div className="lg:col-span-3 space-y-6">
                        <div>
                            {currentStep === 'questions' && <QuestionsStep />}
                            {currentStep === 'where' && <WhereStep />}
                            {currentStep === 'when' && <WhenStep />}
                        </div>

                        <div className="flex items-center justify-end pt-4 border-t border-border">
                            <div className="flex items-center gap-2">
                                {currentStep === 'when' && (
                                    <>
                                        <LemonButton type="secondary" onClick={() => setStep('appearance')}>
                                            Customize appearance
                                        </LemonButton>
                                        <LemonButton
                                            type="secondary"
                                            loading={surveySaving}
                                            disabled={surveyLaunching}
                                            onClick={handleSaveClick}
                                        >
                                            {isEditing ? 'Save changes' : 'Save as draft'}
                                        </LemonButton>
                                    </>
                                )}
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

                        <p className="text-center text-xs text-muted">
                            Need more control?{' '}
                            <button type="button" onClick={handleCustomizeMore} className="text-link hover:underline">
                                Open full editor
                            </button>
                        </p>
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
                                        {`${previewPageIndex + 1} / ${previewSurvey.questions.length + (previewSurvey.appearance?.displayThankYouMessage ? 1 : 0)}`}
                                    </span>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconChevronRight />}
                                        onClick={() => {
                                            const maxIndex = previewSurvey.appearance?.displayThankYouMessage
                                                ? previewSurvey.questions.length
                                                : previewSurvey.questions.length - 1
                                            setPreviewPageIndex(Math.min(maxIndex, previewPageIndex + 1))
                                        }}
                                        disabledReason={
                                            previewPageIndex >=
                                            (previewSurvey.appearance?.displayThankYouMessage
                                                ? previewSurvey.questions.length
                                                : previewSurvey.questions.length - 1)
                                                ? 'Last screen'
                                                : undefined
                                        }
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
