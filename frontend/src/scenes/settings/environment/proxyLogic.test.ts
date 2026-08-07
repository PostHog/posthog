import { MOCK_DEFAULT_USER, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { ProxyRecord, proxyLogic } from './proxyLogic'

const MOCK_IMPERSONATED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_impersonated: true,
}

const mockProxyRecord = (overrides: Partial<ProxyRecord> = {}): ProxyRecord => ({
    id: 'record-1',
    domain: 't.example.com',
    status: 'valid',
    target_cname: 'proxy.posthog.com',
    ...overrides,
})

const proxyRecordsResponse = (records: ProxyRecord[]): { results: ProxyRecord[]; max_proxy_records: number } => ({
    results: records,
    max_proxy_records: 2,
})

const healthyReport = {
    ran_at: '2026-08-07T00:00:00Z',
    summary: { status: 'healthy', primary_issue: null, next_action: null },
    checks: [],
}

describe('proxyLogic', () => {
    let logic: ReturnType<typeof proxyLogic.build>

    beforeEach(() => {
        // cloudflareOptInAcknowledged is persisted to localStorage — wipe it so each test
        // starts from a clean slate and isn't polluted by prior tests' acknowledgments.
        localStorage.clear()
        useMocks({
            get: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records`]: proxyRecordsResponse([]),
            },
        })
        initKeaTests()
        organizationLogic.mount()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function mountLogic(): Promise<void> {
        logic = proxyLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('returns false when the user is impersonating, even with no records and no acknowledgment', async () => {
        userLogic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)
        await mountLogic()

        await expectLogic(logic).toMatchValues({
            cloudflareOptInAcknowledged: false,
            proxyRecords: [],
            shouldShowCloudflareOptIn: false,
        })
    })

    it('returns false when the organization already has proxy records', async () => {
        useMocks({
            get: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records`]: proxyRecordsResponse([mockProxyRecord()]),
            },
        })
        await mountLogic()

        await expectLogic(logic).toMatchValues({
            shouldShowCloudflareOptIn: false,
        })
        expect(logic.values.proxyRecords.length).toBeGreaterThan(0)
    })

    it('returns true for a first-time non-impersonating user with no records and no acknowledgment', async () => {
        await mountLogic()

        await expectLogic(logic).toMatchValues({
            cloudflareOptInAcknowledged: false,
            proxyRecords: [],
            shouldShowCloudflareOptIn: true,
        })
    })

    it('returns false once acknowledgeCloudflareOptIn has been dispatched', async () => {
        await mountLogic()

        await expectLogic(logic).toMatchValues({
            shouldShowCloudflareOptIn: true,
        })

        await expectLogic(logic, () => {
            logic.actions.acknowledgeCloudflareOptIn()
        }).toMatchValues({
            cloudflareOptInAcknowledged: true,
            shouldShowCloudflareOptIn: false,
        })
    })

    it('does not show the banner before the initial records load resolves', () => {
        // Mount synchronously without awaiting toFinishAllListeners — this mimics the
        // first paint after mount, before the proxy_records API call has returned.
        logic = proxyLogic()
        logic.mount()

        expect(logic.values.proxyRecordsLoaded).toBe(false)
        expect(logic.values.shouldShowCloudflareOptIn).toBe(false)
    })

    it('auto-persists acknowledgment when loadRecordsSuccess returns existing records', async () => {
        useMocks({
            get: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records`]: proxyRecordsResponse([mockProxyRecord()]),
            },
        })
        await mountLogic()

        // Records existing on the backend is durable proof of prior consent — the reducer
        // re-persists this via { persist: true } so the banner doesn't flash again on
        // browsers where localStorage was cleared.
        await expectLogic(logic).toMatchValues({
            cloudflareOptInAcknowledged: true,
            shouldShowCloudflareOptIn: false,
        })
    })

    it('arms a cooldown when a diagnostic runs so the menu item disables before a 429 can fire', async () => {
        useMocks({
            post: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records/record-1/diagnose`]: () => [
                    200,
                    healthyReport,
                ],
            },
        })
        await mountLogic()

        await expectLogic(logic, () => {
            logic.actions.diagnose('record-1')
        })
            .toDispatchActions(['diagnose', 'startDiagnoseCooldown', 'diagnoseSuccess'])
            .toMatchValues({ diagnoseCooldownIds: ['record-1'] })
    })

    it('does not surface an error toast when the server returns a 429 cooldown', async () => {
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation((() => undefined) as any)
        useMocks({
            post: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records/record-1/diagnose`]: () => [
                    429,
                    { detail: 'A diagnostic just ran for this proxy. Wait 30 seconds before trying again.' },
                ],
            },
        })
        await mountLogic()

        await expectLogic(logic, () => {
            logic.actions.diagnose('record-1')
        })
            .toDispatchActions(['diagnose', 'diagnoseFailure'])
            .toMatchValues({ diagnoseLoadingIds: [] })

        expect(toastSpy).not.toHaveBeenCalled()
        toastSpy.mockRestore()
    })
})
