import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

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
            ['goToPreviousStep'],
        ],
    }),
    actions({
        setHost: (host: string) => ({ host }),
    }),
    reducers({
        dashboardCreatedDuringOnboarding: [
            null as DashboardType | null,
            {
                submitNewDashboardSuccessWithResult: (_, { result }) => result,
            },
        ],
        host: [
            null as string | null,
            {
                setHost: (_, { host }) => host,
            },
        ],
    }),
    listeners({
        submitNewDashboardSuccessWithResult: ({ result, variables }) => {
            if (result) {
                onboardingLogic.actions.goToNextStep(variables?.length && variables.length > 0 ? 1 : 2)
            }
        },
    }),
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
