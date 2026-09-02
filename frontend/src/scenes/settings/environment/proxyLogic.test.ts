import { MOCK_DEFAULT_USER, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { ProxyRecord, canConfigureRootRedirect, proxyLogic } from './proxyLogic'

const MOCK_IMPERSONATED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_impersonated: true,
}

const mockProxyRecord = (overrides: Partial<ProxyRecord> = {}): ProxyRecord => ({
    id: 'record-1',
    domain: 't.example.com',
    status: 'valid',
    target_cname: 'proxy.posthog.com',
    root_redirect_url: null,
    root_redirect_supported: true,
    message: null,
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
    created_by: 1,
    ...overrides,
})

const proxyRecordsResponse = (records: ProxyRecord[]): { results: ProxyRecord[]; max_proxy_records: number } => ({
    results: records,
    max_proxy_records: 2,
})

describe('proxyLogic — shouldShowCloudflareOptIn', () => {
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
})

describe('proxyLogic — root redirect', () => {
    it.each<[string, boolean, ProxyRecord, boolean]>([
        ['supported valid proxy', true, mockProxyRecord(), true],
        ['supported warning proxy', true, mockProxyRecord({ status: 'warning' }), true],
        ['legacy proxy', true, mockProxyRecord({ root_redirect_supported: false }), false],
        ['disabled feature', false, mockProxyRecord(), false],
        ['proxy that is not ready', true, mockProxyRecord({ status: 'waiting' }), false],
    ])('allows configuration for a %s when expected', (_name, featureEnabled, record, expected) => {
        expect(canConfigureRootRedirect(record, featureEnabled)).toBe(expected)
    })

    it('updates the record from the PATCH response', async () => {
        const record = mockProxyRecord()
        const updatedRecord = mockProxyRecord({ root_redirect_url: 'https://www.example.com/' })
        useMocks({
            get: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records/`]: proxyRecordsResponse([record]),
            },
            patch: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records/${record.id}/`]: updatedRecord,
            },
        })
        initKeaTests()
        organizationLogic.mount()

        const logic = proxyLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.updateRootRedirect({ id: record.id, rootRedirectUrl: 'https://www.example.com/' })
        })
            .toDispatchActions(['updateRootRedirectSuccess'])
            .toMatchValues({ proxyRecords: [updatedRecord] })

        logic.unmount()
    })
})
