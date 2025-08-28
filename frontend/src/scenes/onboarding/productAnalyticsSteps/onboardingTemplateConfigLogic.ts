import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { dashboardTemplateVariablesLogic } from 'scenes/dashboard/dashboardTemplateVariablesLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { DashboardTemplateType, DashboardType, OnboardingStepKey } from '~/types'

import { onboardingLogic } from '../onboardingLogic'
import type { onboardingTemplateConfigLogicType } from './onboardingTemplateConfigLogicType'

// TODO: We should have a variables logic that is keyed for each variable and can handle its state independently.
// Right now we have fields like customEventFieldShown that, if used outside of onboarding, will impact all variables.

export const onboardingTemplateConfigLogic = kea<onboardingTemplateConfigLogicType>([
    path(['scenes', 'onboarding', 'productAnalyticsSteps', 'onboardingTemplateConfigLogic']),
    connect(() => ({
        values: [newDashboardLogic, ['activeDashboardTemplate'], dashboardTemplateVariablesLogic, ['activeVariable']],
        actions: [
            newDashboardLogic,
            ['submitNewDashboardSuccessWithResult', 'setIsLoading'],
            dashboardTemplateVariablesLogic,
            [
                'setActiveVariableIndex',
                'incrementActiveVariableIndex',
                'setActiveVariableCustomEventName',
                'maybeResetActiveVariableCustomEventName',
            ],
            onboardingLogic,
            ['goToPreviousStep', 'setOnCompleteOnboardingRedirectUrl', 'goToNextStep'],
            sidePanelStateLogic,
            ['closeSidePanel'],
        ],
    })),
    actions({
        setDashboardCreatedDuringOnboarding: (dashboard: DashboardType | null) => ({ dashboard }),
        showCustomEventField: true,
        hideCustomEventField: true,
        reportTemplateSelected: (template: DashboardTemplateType) => ({ template }),
        showTemplateRequestModal: true,
        hideTemplateRequestModal: true,
    }),
    reducers({
        dashboardCreatedDuringOnboarding: [
            null as DashboardType | null,
            { persist: true },
            {
                submitNewDashboardSuccessWithResult: (_, { result }) => result,
                setDashboardCreatedDuringOnboarding: (_, { dashboard }) => dashboard,
            },
        ],
        customEventFieldShown: [
            false as boolean,
            {
                showCustomEventField: () => true,
                hideCustomEventField: () => false,
            },
        ],
        isTemplateRequestModalOpen: [
            false as boolean,
            {
                showTemplateRequestModal: () => true,
                hideTemplateRequestModal: () => false,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        templateRequestForm: {
            alwaysShowErrors: true,
            showErrorsOnTouch: true,
            defaults: {
                templateRequest: '',
            },
            errors: ({ templateRequest }) => ({
                templateRequest: !templateRequest
                    ? "Please enter a template you'd like us to add to continue"
                    : undefined,
            }),
            submit: async () => {
                posthog.capture('template requested during onboarding', {
                    template_request: values.templateRequestForm.templateRequest,
                })
                actions.hideTemplateRequestModal()
                actions.resetTemplateRequestForm()
                actions.goToNextStep(2)
            },
        },
    })),
    listeners(({ actions, values }) => ({
        submitNewDashboardSuccessWithResult: ({ result, variables }) => {
            if (result && variables?.length == 0) {
                // dashbboard was created without variables, go to next step for success message
                onboardingLogic.actions.goToNextStep()
            }
            actions.setOnCompleteOnboardingRedirectUrl(urls.dashboard(result.id))
            posthog.capture('dashboard created during onboarding', {
                dashboard_id: result.id,
                creation_mode: result.creation_mode,
                title: result.name,
                has_variables: variables?.length ? variables?.length > 0 : false,
                total_variables: variables?.length || 0,
                variables: variables?.map((v) => v.name),
            })
        },
        reportTemplateSelected: ({ template }) => {
            posthog.capture('template selected during onboarding', {
                template_id: template.id,
                template_name: template.template_name,
                variables: template.variables?.map((v) => v.name),
            })
        },
        setActiveVariableIndex: () => {
            actions.maybeResetActiveVariableCustomEventName()
        },
        incrementActiveVariableIndex: () => {
            actions.maybeResetActiveVariableCustomEventName()
        },
        maybeResetActiveVariableCustomEventName: () => {
            if (values.activeVariable.default?.custom_event) {
                actions.showCustomEventField()
                actions.setActiveVariableCustomEventName(values.activeVariable?.default?.id)
            } else {
                actions.hideCustomEventField()
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/onboarding/:productKey': (_, { step }) => {
            if (step === OnboardingStepKey.DASHBOARD_TEMPLATE_CONFIGURE) {
                if (
                    (!values.activeDashboardTemplate || !values.activeDashboardTemplate.variables) &&
                    // we want to use the "success" part of this configure screen, so if we have a dashboard created
                    // during onboarding, we can view this screen to show the success message. So only go back if we don't have one.
                    !values.dashboardCreatedDuringOnboarding
                ) {
                    actions.goToPreviousStep()
                }
            }
            if (step === OnboardingStepKey.DASHBOARD_TEMPLATE) {
                actions.closeSidePanel()
            }
            actions.setIsLoading(false)
        },
    })),
])
