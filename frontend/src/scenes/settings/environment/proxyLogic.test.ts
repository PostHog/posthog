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

    it('returns false when the organization already has proxy records, regardless of acknowledgment', async () => {
        useMocks({
            get: {
                [`/api/organizations/${MOCK_ORGANIZATION_ID}/proxy_records`]: proxyRecordsResponse([mockProxyRecord()]),
            },
        })
        await mountLogic()

        await expectLogic(logic).toMatchValues({
            cloudflareOptInAcknowledged: false,
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
})
