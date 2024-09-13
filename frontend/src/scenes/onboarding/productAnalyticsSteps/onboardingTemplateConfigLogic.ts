import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { DashboardType } from '~/types'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import type { onboardingTemplateConfigLogicType } from './onboardingTemplateConfigLogicType'

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
    }),
    listeners(({ actions }) => ({
        submitNewDashboardSuccessWithResult: ({ result, variables }) => {
            if (result && variables?.length && variables.length == 0) {
                onboardingLogic.actions.goToNextStep(2)
            }
            actions.setOnCompleteOnboardingRedirectUrl(urls.dashboard(result.id))
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/onboarding/:productKey': (_, { step }) => {
            if (step === OnboardingStepKey.DASHBOARD_TEMPLATE_CONFIGURE) {
                if (!values.activeDashboardTemplate || !values.activeDashboardTemplate.variables) {
                    actions.goToPreviousStep()
                }
            }
            actions.setIsLoading(false)
        },
    })),
])
