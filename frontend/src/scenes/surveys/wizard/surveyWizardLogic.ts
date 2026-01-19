import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { LinkSurveyQuestion, Survey, SurveyQuestionType, SurveySchedule, SurveyType } from '~/types'

import { SurveyTemplate, defaultSurveyAppearance, defaultSurveyTemplates, surveyThemes } from '../constants'
import { surveyLogic } from '../surveyLogic'
import { surveysLogic } from '../surveysLogic'
import type { surveyWizardLogicType } from './surveyWizardLogicType'

export type WizardStep = 'template' | 'questions' | 'where' | 'when' | 'appearance' | 'success'

// Main flow steps (appearance is optional, branched from 'when')
const WIZARD_STEPS: WizardStep[] = ['template', 'questions', 'where', 'when']

// Core templates to show prominently
const CORE_TEMPLATE_TYPES = [
    'Net promoter score (NPS)',
    'Customer satisfaction score (CSAT)',
    'Product-market fit (PMF)',
    'Open feedback',
]

export interface SurveyWizardLogicProps {
    id: string // 'new' for new surveys, or a UUID for editing
}

export const surveyWizardLogic = kea<surveyWizardLogicType>([
    path(['scenes', 'surveys', 'wizard', 'surveyWizardLogic']),

    props({} as SurveyWizardLogicProps),

    key((props) => props.id),

    connect((props: SurveyWizardLogicProps) => ({
        actions: [
            surveyLogic({ id: props.id }),
            ['setSurveyValue', 'resetSurvey', 'loadSurvey'],
            surveysLogic,
            ['loadSurveys'],
            eventUsageLogic,
            ['reportSurveyCreated', 'reportSurveyEdited'],
        ],
        values: [surveyLogic({ id: props.id }), ['survey', 'surveyLoading']],
    })),

    actions({
        setStep: (step: WizardStep) => ({ step }),
        nextStep: true,
        prevStep: true,
        resetWizard: true,
        selectTemplate: (template: SurveyTemplate) => ({ template }),
        restoreDefaultQuestions: true,
        launchSurvey: true,
        launchSurveySuccess: (survey: Survey) => ({ survey }),
        launchSurveyFailure: (error: string) => ({ error }),
        saveDraft: true,
        saveDraftSuccess: (survey: Survey) => ({ survey }),
        saveDraftFailure: (error: string) => ({ error }),
        updateSurvey: true,
        updateSurveySuccess: (survey: Survey) => ({ survey }),
        updateSurveyFailure: (error: string) => ({ error }),
    }),

    reducers(({ props }) => ({
        currentStep: [
            // Start at 'questions' when editing, 'template' when creating new
            (props.id === 'new' ? 'template' : 'questions') as WizardStep,
            {
                setStep: (_, { step }) => step,
                nextStep: (state) => {
                    const currentIndex = WIZARD_STEPS.indexOf(state)
                    return WIZARD_STEPS[Math.min(currentIndex + 1, WIZARD_STEPS.length - 1)]
                },
                prevStep: (state) => {
                    const currentIndex = WIZARD_STEPS.indexOf(state)
                    return WIZARD_STEPS[Math.max(currentIndex - 1, 0)]
                },
                resetWizard: () => (props.id === 'new' ? 'template' : 'questions'),
                selectTemplate: () => 'questions', // Move to questions after selecting template
            },
        ],
        selectedTemplate: [
            null as SurveyTemplate | null,
            {
                selectTemplate: (_, { template }) => template,
                resetWizard: () => null,
            },
        ],
        createdSurvey: [
            null as Survey | null,
            {
                launchSurveySuccess: (_, { survey }) => survey,
                updateSurveySuccess: (_, { survey }) => survey,
                resetWizard: () => null,
            },
        ],
        surveyLaunching: [
            false,
            {
                launchSurvey: () => true,
                launchSurveySuccess: () => false,
                launchSurveyFailure: () => false,
            },
        ],
        surveySaving: [
            false,
            {
                saveDraft: () => true,
                saveDraftSuccess: () => false,
                saveDraftFailure: () => false,
                updateSurvey: () => true,
                updateSurveySuccess: () => false,
                updateSurveyFailure: () => false,
            },
        ],
    })),

    selectors({
        coreTemplates: [
            () => [],
            (): SurveyTemplate[] => {
                return defaultSurveyTemplates.filter((t) => CORE_TEMPLATE_TYPES.includes(t.templateType))
            },
        ],
        otherTemplates: [
            () => [],
            (): SurveyTemplate[] => {
                return defaultSurveyTemplates.filter((t) => !CORE_TEMPLATE_TYPES.includes(t.templateType))
            },
        ],
        stepNumber: [
            (s) => [s.currentStep],
            (currentStep: WizardStep): number => {
                const index = WIZARD_STEPS.indexOf(currentStep)
                // Template step is step 0, so questions is step 1
                return index
            },
        ],
        stepValidationErrors: [
            (s) => [s.survey],
            (survey: Survey): Record<WizardStep, string[]> => {
                const errors: Record<WizardStep, string[]> = {
                    template: [],
                    questions: [],
                    where: [],
                    when: [],
                    appearance: [],
                    success: [],
                }

                // Validate questions step
                if (survey.questions) {
                    for (const question of survey.questions) {
                        if (question.type === SurveyQuestionType.Link) {
                            const linkQuestion = question as LinkSurveyQuestion
                            const link = linkQuestion.link || ''
                            if (link && !link.startsWith('https://') && !link.startsWith('mailto:')) {
                                errors.questions.push('Link URLs must start with https:// or mailto:')
                                break // Only show one error
                            }
                        }
                    }
                }

                return errors
            },
        ],
        currentStepHasErrors: [
            (s) => [s.stepValidationErrors, s.currentStep],
            (errors: Record<WizardStep, string[]>, currentStep: WizardStep): boolean => {
                return errors[currentStep]?.length > 0
            },
        ],
        recommendedFrequency: [
            (s) => [s.selectedTemplate],
            (template: SurveyTemplate | null): { value: string; label: string; reason: string } => {
                const templateType = template?.templateType
                if (templateType?.includes('NPS') || templateType?.includes('PMF')) {
                    return {
                        value: 'quarterly',
                        label: 'Every 3 months',
                        reason: 'Relationship metrics work best quarterly',
                    }
                }
                if (templateType?.includes('CSAT') || templateType?.includes('CES')) {
                    return {
                        value: 'monthly',
                        label: 'Every month',
                        reason: 'Transactional surveys can be more frequent',
                    }
                }
                if (templateType?.includes('Onboarding') || templateType?.includes('Attribution')) {
                    return { value: 'once', label: 'Once ever', reason: 'One-time feedback collection' }
                }
                return { value: 'monthly', label: 'Every month', reason: 'General feedback cadence' }
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        selectTemplate: ({ template }) => {
            // Initialize survey with selected template
            const timestamp = new Date().toISOString().slice(0, 16).replace('T', ' ')
            actions.setSurveyValue('name', `${template.templateType} (${timestamp})`)
            actions.setSurveyValue('description', template.description || '')
            actions.setSurveyValue('type', template.type || SurveyType.Popover)
            actions.setSurveyValue('questions', template.questions)

            // Apply Clean theme by default (works well on most sites, and users without
            // styling access are stuck with the default, so light-friendly is safer)
            // Only take behavioral (non-color) properties from template appearance
            const defaultTheme = surveyThemes.find((t) => t.id === 'clean')
            const themeAppearance = defaultTheme?.appearance || {}

            // Extract only behavioral properties from template (not colors)
            const templateBehavior = template.appearance
                ? {
                      displayThankYouMessage: template.appearance.displayThankYouMessage,
                      thankYouMessageHeader: template.appearance.thankYouMessageHeader,
                      position: template.appearance.position,
                      shuffleQuestions: template.appearance.shuffleQuestions,
                      surveyPopupDelaySeconds: template.appearance.surveyPopupDelaySeconds,
                  }
                : {}
            // Remove undefined values
            const cleanTemplateBehavior = Object.fromEntries(
                Object.entries(templateBehavior).filter(([_, v]) => v !== undefined)
            )

            actions.setSurveyValue('appearance', {
                ...defaultSurveyAppearance,
                ...themeAppearance,
                ...cleanTemplateBehavior,
            })

            // Set frequency based on template type, but preserve other conditions from template
            const frequencyToDays: Record<string, number | undefined> = {
                once: undefined,
                yearly: 365,
                quarterly: 90,
                monthly: 30,
            }
            const templateType = template.templateType
            let frequencyValue = 'monthly'
            if (templateType.includes('NPS') || templateType.includes('PMF')) {
                frequencyValue = 'quarterly'
            } else if (templateType.includes('CSAT') || templateType.includes('CES')) {
                frequencyValue = 'monthly'
            } else if (templateType.includes('Onboarding') || templateType.includes('Attribution')) {
                frequencyValue = 'once'
            }

            const isOnce = frequencyValue === 'once'
            actions.setSurveyValue('schedule', isOnce ? SurveySchedule.Once : SurveySchedule.Always)
            // Preserve existing template conditions (e.g. event triggers) and only update frequency
            actions.setSurveyValue('conditions', {
                ...template.conditions,
                seenSurveyWaitPeriodInDays: frequencyToDays[frequencyValue],
            })
        },
        restoreDefaultQuestions: () => {
            const template = values.selectedTemplate
            if (template) {
                actions.setSurveyValue('questions', template.questions)
                lemonToast.success('Questions restored to defaults')
            }
        },
        launchSurvey: async () => {
            try {
                const surveyData = {
                    ...values.survey,
                    start_date: new Date().toISOString(),
                }
                const createdSurvey = await api.surveys.create(surveyData)
                actions.launchSurveySuccess(createdSurvey)
            } catch (e) {
                actions.launchSurveyFailure(String(e))
                lemonToast.error('Failed to create survey')
            }
        },
        launchSurveySuccess: ({ survey }) => {
            lemonToast.success(`Survey ${survey.name} created`)
            actions.loadSurveys()
            actions.reportSurveyCreated(survey, false, 'wizard')
            actions.setStep('success')
        },
        saveDraft: async () => {
            try {
                const surveyData = {
                    ...values.survey,
                    // Don't set start_date - keep as draft
                }
                const createdSurvey = await api.surveys.create(surveyData)
                actions.saveDraftSuccess(createdSurvey)
            } catch (e) {
                actions.saveDraftFailure(String(e))
                lemonToast.error('Failed to save draft')
            }
        },
        saveDraftSuccess: ({ survey }) => {
            lemonToast.success(`Survey "${survey.name}" saved as draft`)
            actions.loadSurveys()
            actions.reportSurveyCreated(survey, false, 'wizard')
            router.actions.push(urls.survey(survey.id))
        },
        updateSurvey: async () => {
            try {
                const surveyData = values.survey
                const updatedSurvey = await api.surveys.update(props.id, surveyData)
                actions.updateSurveySuccess(updatedSurvey)
            } catch (e) {
                actions.updateSurveyFailure(String(e))
                lemonToast.error('Failed to update survey')
            }
        },
        updateSurveySuccess: ({ survey }) => {
            lemonToast.success(`Survey "${survey.name}" updated`)
            actions.loadSurveys()
            actions.reportSurveyEdited(survey)
            router.actions.push(urls.survey(survey.id))
        },
    })),

    afterMount(({ actions, props, values }) => {
        if (props.id === 'new') {
            // Check if survey already has a template selected (from SurveyTemplates page)
            // Templates set both name AND questions, while default NEW_SURVEY has empty name
            const hasTemplateSelected = values.survey?.name && values.survey?.questions?.length > 0
            if (hasTemplateSelected) {
                // Skip template step, go directly to questions
                actions.setStep('questions')
            } else {
                // Reset wizard and survey state for new survey
                actions.resetWizard()
                actions.resetSurvey()
            }
        } else {
            // Load existing survey data
            actions.loadSurvey()
        }

        return () => {
            actions.resetWizard()
        }
    }),
])
