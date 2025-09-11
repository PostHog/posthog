import { MOCK_TEAM_ID } from 'lib/api.mock'

import { dayjs } from 'lib/dayjs'
import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AppContext, TeamType } from '~/types'

import { hogql } from './utils'

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
        const context = getAppContext()
        let oldTimezone = context?.current_team?.timezone || 'UTC'
        if (context?.current_team) {
            context.current_team.timezone = 'Europe/Moscow'
        }
        teamLogic.actions.loadCurrentTeamSuccess({ id: MOCK_TEAM_ID, timezone: 'Europe/Moscow' } as TeamType)
        expect(hogql`SELECT * FROM events WHERE timestamp > ${dayjs('2023-04-04T04:04:00Z')}`).toEqual(
            "SELECT * FROM events WHERE timestamp > '2023-04-04 07:04:00'" // Offset by 3 hours
        )
        if (context?.current_team) {
            context.current_team.timezone = oldTimezone
        }
    })
})
