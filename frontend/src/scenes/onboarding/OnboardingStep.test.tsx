import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { billingLogic } from 'lib/logic/billing/billingLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { OnboardingStepKey, Realm, Region } from '~/types'

import { onboardingLogic } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

describe('OnboardingStep', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = onboardingLogic()
        logic.mount()
        preflightLogic.actions.loadPreflightSuccess({
            ...preflightJson,
            cloud: true,
            realm: Realm.Cloud,
            region: Region.US,
            slack_service: { available: false },
            data_warehouse_integrations: { hubspot: {}, salesforce: {} },
            wizard_cloud_run_available: false,
        })
        billingLogic.actions.loadBillingSuccess(billingUnsubscribedJson)
        logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
        logic.actions.setSecondaryProductKeys([ProductKey.WEB_ANALYTICS])
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        [OnboardingStepKey.INSTALL, null],
        [OnboardingStepKey.PRODUCT_CONFIGURATION, 'install:product_analytics'],
        [OnboardingStepKey.LINK_DATA, 'session_replay:product_analytics'],
        [OnboardingStepKey.PLANS, 'link_data:product_analytics'],
        [OnboardingStepKey.INVITE_TEAMMATES, 'plans:product_analytics'],
    ])('can go back from %s without completing or skipping the step', (stepKey, previousStepId) => {
        logic.actions.setStepId(`${stepKey}:product_analytics`)
        const visitedStepIds = [...logic.values.visitedStepIds]
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        render(
            <OnboardingStep title="Onboarding" stepKey={stepKey}>
                Step content
            </OnboardingStep>
        )

        if (!previousStepId) {
            expect(screen.queryByLabelText('Back')).not.toBeInTheDocument()
            return
        }

        fireEvent.click(screen.getByLabelText('Back'))

        expect(logic.values.stepId).toBe(previousStepId)
        expect(logic.values.secondaryProductKeys).toEqual([ProductKey.WEB_ANALYTICS])
        expect(logic.values.visitedStepIds).toEqual(expect.arrayContaining(visitedStepIds))
        expect(logic.values.isCompleting).toBe(false)
        expect(capture).toHaveBeenCalledWith('onboarding step back', {
            step_key: stepKey,
            product_key: ProductKey.PRODUCT_ANALYTICS,
            version: 1,
            flow_variant: 'legacy',
            entry_point: 'product_selection',
        })
        expect(capture).not.toHaveBeenCalledWith('onboarding step completed', expect.anything())
        expect(capture).not.toHaveBeenCalledWith('onboarding step skipped', expect.anything())
    })

    it('prevents going back while onboarding is completing', () => {
        logic.actions.setStepId('invite_teammates:product_analytics')
        logic.actions.setIsCompleting(true)
        render(
            <OnboardingStep title="Onboarding" stepKey={OnboardingStepKey.INVITE_TEAMMATES}>
                Step content
            </OnboardingStep>
        )

        expect(screen.getByLabelText('Back').closest('button')).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(screen.getByLabelText('Back'))
        expect(logic.values.stepId).toBe('invite_teammates:product_analytics')
    })
})
