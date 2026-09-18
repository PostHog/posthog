import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { uuid } from 'lib/utils/dom'
import { getAppContext } from 'lib/utils/getAppContext'

import { createCustomerJourney, CustomerJourney, CustomerJourneyOptions } from './createCustomerJourney'
import { CustomerJourneyEnrollment, getCustomerJourneyEligibility } from './customerJourneyEligibility'

function getRuntimeCustomerJourneyEnrollment(): CustomerJourneyEnrollment | null {
    try {
        const appContext = getAppContext()
        if (!appContext?.preflight.cloud) {
            return null
        }
        const flag = posthog.getFeatureFlagResult(FEATURE_FLAGS.CUSTOMER_JOURNEY_TELEMETRY, { send_event: false })
        return getCustomerJourneyEligibility(flag?.variant ?? flag?.enabled, flag?.payload, {
            region: appContext.preflight.region,
            project_id: appContext.current_team?.id,
            organization_id: appContext.current_team?.organization,
        })
    } catch {
        return null
    }
}

export function isCustomerJourneyTelemetryEnabled(): boolean {
    return getRuntimeCustomerJourneyEnrollment() !== null
}

export function startCustomerJourney(options: CustomerJourneyOptions): CustomerJourney | null {
    try {
        const scope = getRuntimeCustomerJourneyEnrollment()
        if (!scope) {
            return null
        }
        return createCustomerJourney(
            { ...options, ...scope, attempt_id: options.attempt_id ?? uuid() },
            {
                now: () => performance.now(),
                capture: (event, properties) => posthog.capture(event, properties) !== undefined,
                visibility: {
                    getState: () => document.visibilityState,
                    subscribe: (listener) => {
                        document.addEventListener('visibilitychange', listener)
                        return () => document.removeEventListener('visibilitychange', listener)
                    },
                },
            }
        )
    } catch {
        // Missing bootstrap or telemetry state must not prevent customer work.
        return null
    }
}
