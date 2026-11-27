import { ticketListUrl } from './supportOverviewQueries'

describe('supportOverviewQueries', () => {
    const openStatuses = 'status=%5B%22new%22%2C%22open%22%2C%22pending%22%2C%22on_hold%22%5D'

    test.each([
        ['open', `/support/tickets?${openStatuses}`],
        ['unassigned', `/support/tickets?${openStatuses}&assignee=unassigned`],
        ['slaAtRisk', `/support/tickets?${openStatuses}&sla=at-risk&order_by=sla_due_at`],
        ['slaBreached', `/support/tickets?${openStatuses}&sla=breached&order_by=sla_due_at`],
    ] as const)('the %s card links to the matching ticket list filters', (key, url) => {
        expect(ticketListUrl(key)).toEqual(url)
    })
})
