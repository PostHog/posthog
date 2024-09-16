import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'
import posthog from 'posthog-js'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { DashboardTemplateType, DashboardType } from '~/types'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import type { onboardingTemplateConfigLogicType } from './onboardingTemplateConfigLogicType'

// TODO: We should have a variables logic that is keyed for each variable and can handle its state independently.
// Right now we have fields like customEventFieldShown that, if used outside of onboarding, will impact all variables.

export const onboardingTemplateConfigLogic = kea<onboardingTemplateConfigLogicType>([
    path(['scenes', 'onboarding', 'productAnalyticsSteps', 'onboardingTemplateConfigLogic']),
    connect({
        values: [newDashboardLogic, ['activeDashboardTemplate']],
        actions: [
            newDashboardLogic,
            ['submitNewDashboardSuccessWithResult', 'setIsLoading'],
            onboardingLogic,
            ['goToPreviousStep', 'setOnCompleteOnboardingRedirectUrl'],
        ],
    }),
    actions({
        setDashboardCreatedDuringOnboarding: (dashboard: DashboardType | null) => ({ dashboard }),
        showCustomEventField: true,
        hideCustomEventField: true,
        reportTemplateSelected: (template: DashboardTemplateType) => ({ template }),
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
            false,
            {
                showCustomEventField: () => true,
                hideCustomEventField: () => false,
            },
        ],
    }),
    listeners(({ actions }) => ({
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
                template_name: template.name,
                variables: template.variables?.map((v) => v.name),
            })
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
            actions.setIsLoading(false)
        },
    })),
])
