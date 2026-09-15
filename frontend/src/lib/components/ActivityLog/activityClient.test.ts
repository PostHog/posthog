import { describeActivityClient } from 'lib/components/ActivityLog/activityClient'

describe('describeActivityClient', () => {
    it.each([
        ['mcp', 'MCP'],
        ['posthog-python', 'posthog-python'],
        ['scout:self-driving-dwh', 'scout self-driving-dwh'],
    ])('labels %s as %s', (client, expected) => {
        expect(describeActivityClient(client).label).toEqual(expected)
    })

    it('tells a scout apart from a self-reported client', () => {
        expect(describeActivityClient('scout:self-driving-dwh').tooltip).toContain('not self-reported')
        expect(describeActivityClient('mcp').tooltip).toContain('x-posthog-client')
    })
})
