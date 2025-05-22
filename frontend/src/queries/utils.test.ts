import { MOCK_TEAM_ID } from 'lib/api.mock'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AppContext, TeamType } from '~/types'

jest.mock('./latest-versions', () => {
    return {
        LATEST_VERSIONS: {
            FunnelsQuery: 3,
            EventsNode: 5,
            InsightVizNode: 7,
        },
    }
})

jest.resetModules()

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { getFreshQuery, hogql } = require('./utils')

window.POSTHOG_APP_CONTEXT = { current_team: { id: MOCK_TEAM_ID } } as unknown as AppContext

describe('hogql tag', () => {
    initKeaTests()
    teamLogic.mount()

    it('properly returns query with no substitutions', () => {
        expect(hogql`SELECT * FROM events`).toEqual('SELECT * FROM events')
    })

    it('properly returns query with simple identifier substition', () => {
        expect(hogql`SELECT * FROM ${hogql.identifier('events')}`).toEqual('SELECT * FROM events')
    })

    it('properly returns query with escaped identifier substition', () => {
        expect(hogql`SELECT properties.${hogql.identifier('odd property')} FROM events`).toEqual(
            'SELECT properties."odd property" FROM events'
        )
    })

    it('properly returns query with string and number substitutions', () => {
        expect(hogql`SELECT * FROM events WHERE properties.foo = ${'bar'} AND properties.baz = ${3}`).toEqual(
            "SELECT * FROM events WHERE properties.foo = 'bar' AND properties.baz = 3"
        )
    })

    it('properly returns query with string array substitution', () => {
        expect(hogql`SELECT * FROM events WHERE properties.foo IN ${['bar', 'baz']}`).toEqual(
            "SELECT * FROM events WHERE properties.foo IN ['bar', 'baz']"
        )
    })

    it('properly returns query with date substitution in UTC', () => {
        teamLogic.actions.loadCurrentTeamSuccess({ id: MOCK_TEAM_ID, timezone: 'UTC' } as TeamType)
        expect(hogql`SELECT * FROM events WHERE timestamp > ${dayjs('2023-04-04T04:04:00Z')}`).toEqual(
            "SELECT * FROM events WHERE timestamp > '2023-04-04 04:04:00'"
        )
    })

    it('properly returns query with date substitution in non-UTC', () => {
        teamLogic.actions.loadCurrentTeamSuccess({ id: MOCK_TEAM_ID, timezone: 'Europe/Moscow' } as TeamType)
        expect(hogql`SELECT * FROM events WHERE timestamp > ${dayjs('2023-04-04T04:04:00Z')}`).toEqual(
            "SELECT * FROM events WHERE timestamp > '2023-04-04 07:04:00'" // Offset by 3 hours
        )
    })
})

describe('getFreshQuery', () => {
    it('adds the latest version', () => {
        const query = {
            kind: 'InsightVizNode',
            source: {
                kind: 'FunnelsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        name: '$pageview',
                    },
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        name: 'Pageview',
                    },
                ],
                funnelsFilter: {
                    funnelVizType: 'steps',
                },
            },
            full: true,
        }

        expect(getFreshQuery(query)).toEqual({
            full: true,
            kind: 'InsightVizNode',
            source: {
                funnelsFilter: { funnelVizType: 'steps' },
                kind: 'FunnelsQuery',
                series: [
                    { event: '$pageview', kind: 'EventsNode', name: '$pageview', version: 5 },
                    { event: '$pageview', kind: 'EventsNode', name: 'Pageview', version: 5 },
                ],
                version: 3,
            },
            version: 7,
        })
    })
})
