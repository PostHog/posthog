import posthog from 'posthog-js'

import { getAppContext } from 'lib/utils/getAppContext'

import { isCustomerJourneyTelemetryEnabled, startCustomerJourney } from './startCustomerJourney'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { getFeatureFlagResult: jest.fn(), capture: jest.fn(() => ({})) },
}))
jest.mock('lib/utils/getAppContext', () => ({ getAppContext: jest.fn() }))

const options = {
    journey_name: 'experiment_refresh',
    resource_type: 'experiment',
    resource_id: 'synthetic-experiment',
    trigger: 'initial_load',
    readiness_contract_version: 1,
    readiness_scope: 'modern_experiment_results',
} as const

function enableJourney(): void {
    jest.mocked(getAppContext).mockReturnValue({
        current_team: { id: 101, organization: 'synthetic-organization' },
        preflight: { cloud: true, region: 'US' },
    } as ReturnType<typeof getAppContext>)
    jest.mocked(posthog.getFeatureFlagResult).mockReturnValue({
        key: 'customer-journey-telemetry',
        enabled: true,
        variant: undefined,
        payload: {
            schema_version: 1,
            registry_version: 'test-v1',
            organizations: [{ region: 'US', organization_id: 'synthetic-organization' }],
        },
    })
}

describe('startCustomerJourney', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(posthog.getFeatureFlagResult).mockReset()
        enableJourney()
        jest.mocked(posthog.capture).mockReturnValue({} as NonNullable<ReturnType<typeof posthog.capture>>)
    })

    it.each([
        ['enrolled organization', undefined, true],
        ['multivariate flag', 'variant', false],
        ['malformed payload', 'payload', false],
        ['organization switched', 'organization', false],
        ['SDK unavailable', 'sdk', false],
        ['bootstrap unavailable', 'bootstrap', false],
    ] as const)('gates observers without capture for %s', (_, invalid, expected) => {
        const flag = posthog.getFeatureFlagResult('customer-journey-telemetry', { send_event: false })!
        if (invalid === 'variant') {
            jest.mocked(posthog.getFeatureFlagResult).mockReturnValue({ ...flag, variant: 'synthetic-variant' })
        } else if (invalid === 'payload') {
            jest.mocked(posthog.getFeatureFlagResult).mockReturnValue({ ...flag, payload: {} })
        } else if (invalid === 'organization') {
            const context = getAppContext()!
            jest.mocked(getAppContext).mockReturnValue({
                ...context,
                current_team: { ...context.current_team!, organization: 'synthetic-other-organization' },
            })
        } else if (invalid === 'sdk') {
            jest.mocked(posthog.getFeatureFlagResult).mockImplementationOnce(() => {
                throw new Error('synthetic error')
            })
        } else if (invalid === 'bootstrap') {
            jest.mocked(getAppContext).mockReturnValue(undefined)
        }
        expect(isCustomerJourneyTelemetryEnabled()).toBe(expected)
        expect(posthog.capture).not.toHaveBeenCalled()
        for (const call of jest.mocked(posthog.getFeatureFlagResult).mock.calls) {
            expect(call).toEqual(['customer-journey-telemetry', { send_event: false }])
        }
    })

    it('uses the supplied action ID and pins eligibility context until completion', () => {
        const journey = startCustomerJourney({ ...options, attempt_id: 'synthetic-query-action' })!
        jest.mocked(getAppContext).mockReturnValue(undefined)
        journey.finish('usable')
        expect(journey.attemptId).toBe('synthetic-query-action')
        expect(posthog.capture).toHaveBeenCalledTimes(2)
        expect(posthog.capture).toHaveBeenLastCalledWith(
            'customer_journey_finished',
            expect.objectContaining({
                project_id: 101,
                organization_id: 'synthetic-organization',
                attempt_id: 'synthetic-query-action',
                outcome: 'usable',
            })
        )
        expect(posthog.getFeatureFlagResult).toHaveBeenCalledTimes(1)
        expect(posthog.getFeatureFlagResult).toHaveBeenCalledWith('customer-journey-telemetry', { send_event: false })
    })

    it('creates a scoped action ID only when absent and removes the visibility listener on disposal', () => {
        const add = jest.spyOn(document, 'addEventListener')
        const remove = jest.spyOn(document, 'removeEventListener')
        const journey = startCustomerJourney(options)!
        expect(journey.attemptId).toMatch(/^[a-f0-9-]{36}$/)
        const visibilityListener = add.mock.calls.find(([name]) => name === 'visibilitychange')![1]
        journey.dispose('observation_stopped')
        journey.dispose('exited')
        expect(remove).toHaveBeenCalledWith('visibilitychange', visibilityListener)
        expect(posthog.capture).toHaveBeenCalledTimes(2)
        add.mockRestore()
        remove.mockRestore()
    })

    it.each([
        'missing flag',
        'multivariate flag',
        'flag evaluation throws',
        'capture silently drops',
        'self hosted',
    ] as const)('does not interrupt the product or emit an unmatched finish when %s', (failure) => {
        if (failure === 'missing flag') {
            jest.mocked(posthog.getFeatureFlagResult).mockReturnValue(undefined)
        } else if (failure === 'multivariate flag') {
            const flag = posthog.getFeatureFlagResult('customer-journey-telemetry')!
            jest.mocked(posthog.getFeatureFlagResult).mockReturnValue({ ...flag, variant: 'synthetic-variant' })
        } else if (failure === 'flag evaluation throws') {
            jest.mocked(posthog.getFeatureFlagResult).mockImplementationOnce(() => {
                throw new Error('synthetic error')
            })
        } else if (failure === 'capture silently drops') {
            jest.mocked(posthog.capture).mockReturnValueOnce(undefined)
        } else {
            jest.mocked(getAppContext).mockReturnValue({
                current_team: { id: 101, organization: 'synthetic-organization' },
                preflight: { cloud: false, region: 'US' },
            } as ReturnType<typeof getAppContext>)
        }
        expect(startCustomerJourney(options)).toBeNull()
        expect(posthog.capture).toHaveBeenCalledTimes(failure === 'capture silently drops' ? 1 : 0)
    })
})
