import { MOCK_DEFAULT_USER, MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

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

describe('proxyLogic — deleteRecord', () => {
    let logic: ReturnType<typeof proxyLogic.build>

    const recordsPath = `/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records`
    const deletePath = `${recordsPath}/record-1`

    beforeEach(() => {
        localStorage.clear()
    })

    afterEach(() => {
        logic?.unmount()
    })

    async function mount(): Promise<void> {
        initKeaTests()
        organizationLogic.mount()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        logic = proxyLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('surfaces a failed delete and keeps the record instead of swallowing the error', async () => {
        useMocks({
            get: {
                [recordsPath]: proxyRecordsResponse([mockProxyRecord({ id: 'record-1', status: 'waiting' })]),
            },
            delete: {
                [deletePath]: () => [403, { code: 'permission_denied', detail: 'Not allowed' }],
            },
        })
        await mount()

        await expectLogic(logic, () => {
            logic.actions.deleteRecord('record-1')
        }).toDispatchActions(['deleteRecord', 'deleteRecordFailure', 'loadRecords'])

        // A failed delete must leave the row visible — removing it would hide that nothing happened.
        expect(logic.values.proxyRecords.map((r) => r.id)).toContain('record-1')
    })

    it('removes the record and reloads once the delete succeeds', async () => {
        let deleted = false
        useMocks({
            get: {
                [recordsPath]: () =>
                    deleted
                        ? [200, proxyRecordsResponse([])]
                        : [200, proxyRecordsResponse([mockProxyRecord({ id: 'record-1', status: 'waiting' })])],
            },
            delete: {
                [deletePath]: () => {
                    deleted = true
                    return [204, {}]
                },
            },
        })
        await mount()

        await expectLogic(logic, () => {
            logic.actions.deleteRecord('record-1')
        }).toDispatchActions(['deleteRecord', 'deleteRecordSuccess', 'loadRecords', 'loadRecordsSuccess'])

        expect(logic.values.proxyRecords).toEqual([])
    })
})
