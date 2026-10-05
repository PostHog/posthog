import { BuiltLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { partnerBillingInvoicesLogic } from './partnerBillingInvoicesLogic'
import { partnerBillingOrganizationsLogic } from './partnerBillingOrganizationsLogic'
import { partnerBillingSettlementsLogic } from './partnerBillingSettlementsLogic'

const PROPS = { applicationId: '0192d7c4-5b6e-7000-8000-00000000a001' }
const CUSTOMER_ORGANIZATION_ID = '0192d7c4-5b6e-7000-8000-00000000c001'

interface MountedTable {
    logic: BuiltLogic
    setPage: (page: number) => void
}

describe('partner billing pagination', () => {
    let requests: URL[]

    const requestsTo = (table: string): Record<string, string>[] =>
        requests
            .filter((url) => url.pathname.endsWith(`/${table}/`))
            .map((url) => Object.fromEntries(url.searchParams.entries()))

    beforeEach(() => {
        requests = []
        const recordPage = ({ request }: { request: Request }): [number, Record<string, unknown>] => {
            requests.push(new URL(request.url))
            return [200, { count: 45, results: [] }]
        }
        useMocks({
            get: {
                '/api/organizations/:organization_id/partner_billing/:id/': { billing_enabled: true },
                '/api/organizations/:organization_id/partner_billing/:id/organizations/': recordPage,
                '/api/organizations/:organization_id/partner_billing/:id/invoices/': recordPage,
                '/api/organizations/:organization_id/partner_billing/:id/settlements/': recordPage,
            },
        })
        initKeaTests()
    })

    it.each<[string, () => MountedTable]>([
        [
            'organizations',
            () => {
                const logic = partnerBillingOrganizationsLogic(PROPS)
                logic.mount()
                return { logic, setPage: logic.actions.setOrganizationsPage }
            },
        ],
        [
            'invoices',
            () => {
                const logic = partnerBillingInvoicesLogic(PROPS)
                logic.mount()
                return { logic, setPage: logic.actions.setInvoicesPage }
            },
        ],
        [
            'settlements',
            () => {
                const logic = partnerBillingSettlementsLogic(PROPS)
                logic.mount()
                return { logic, setPage: logic.actions.setSettlementsPage }
            },
        ],
    ])('asks for the %s one page at a time', async (table, mountTable) => {
        const { logic, setPage } = mountTable()
        await expectLogic(logic).toFinishAllListeners()

        setPage(3)
        await expectLogic(logic).toFinishAllListeners()

        expect(requestsTo(table)).toEqual([
            { limit: '20', offset: '0' },
            { limit: '20', offset: '40' },
        ])
        logic.unmount()
    })

    it('starts the invoices over at the first page when a filter changes, and sends the filters', async () => {
        const logic = partnerBillingInvoicesLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setInvoicesPage(2)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setInvoiceStatusFilter('open')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setInvoiceOrganizationFilter({
            organizationId: CUSTOMER_ORGANIZATION_ID,
            name: 'Example Customer',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(requestsTo('invoices')).toEqual([
            { limit: '20', offset: '0' },
            { limit: '20', offset: '20' },
            { limit: '20', offset: '0', status: 'open' },
            { limit: '20', offset: '0', status: 'open', organization_id: CUSTOMER_ORGANIZATION_ID },
        ])
        logic.unmount()
    })
})
