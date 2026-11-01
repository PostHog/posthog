import { MOCK_TEAM_ID } from 'lib/api.mock'

import { dayjs } from 'lib/dayjs'
import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AppContext, TeamType } from '~/types'

import { escapeDottedHogQLIdentifier, escapeHogQLString, escapePropertyAsHogQLIdentifier, hogql } from './hogql'

window.POSTHOG_APP_CONTEXT = { current_team: { id: MOCK_TEAM_ID } } as unknown as AppContext

describe('hogql tag', () => {
    // In beforeEach (not describe scope): mounting at collection time fires the preflight
    // load before the MSW harness's beforeAll has installed its fetch stub
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

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

    it('properly escapes single quotes in string values', () => {
        expect(hogql`SELECT * FROM events WHERE properties.name = ${"O'Reilly"}`).toEqual(
            "SELECT * FROM events WHERE properties.name = 'O\\'Reilly'"
        )
    })

    it('properly escapes backslashes in string values', () => {
        expect(hogql`SELECT * FROM events WHERE properties.path = ${'C:\\Users\\test'}`).toEqual(
            "SELECT * FROM events WHERE properties.path = 'C:\\\\Users\\\\test'"
        )
    })
})

describe('escapeHogQLString', () => {
    it.each([
        ['simple', "'simple'"],
        ["O'Reilly", "'O\\'Reilly'"],
        ["'; DROP TABLE users; --", "'\\'; DROP TABLE users; --'"],
        ['C:\\Users\\test', "'C:\\\\Users\\\\test'"],
        ['line1\nline2', "'line1\\nline2'"],
        ['tab\there', "'tab\\there'"],
        ['carriage\rreturn', "'carriage\\rreturn'"],
        ['', "''"],
        ["multiple'quotes'here", "'multiple\\'quotes\\'here'"],
        ['back\\slash', "'back\\\\slash'"],
    ])('escapes %s to %s', (input, expected) => {
        expect(escapeHogQLString(input)).toEqual(expected)
    })
})

describe('escapePropertyAsHogQLIdentifier', () => {
    it('leaves simple identifiers unquoted', () => {
        expect(escapePropertyAsHogQLIdentifier('browser')).toEqual('browser')
        expect(escapePropertyAsHogQLIdentifier('$browser')).toEqual('$browser')
    })

    it('double-quotes identifiers with special characters but no double quote', () => {
        expect(escapePropertyAsHogQLIdentifier('order items')).toEqual('"order items"')
    })

    it('backtick-wraps identifiers containing a double quote', () => {
        expect(escapePropertyAsHogQLIdentifier('a"b')).toEqual('`a"b`')
    })

    it('doubles inner backticks when an identifier has both a double quote and a backtick', () => {
        // Backslash-escaping (`a"b\`c`) would be rejected by the HogQL parser; doubling round-trips.
        expect(escapePropertyAsHogQLIdentifier('a"b`c')).toEqual('`a"b``c`')
    })

    it('escapes backslashes so they survive the parser instead of forming an escape sequence', () => {
        expect(escapePropertyAsHogQLIdentifier('a\\b')).toEqual('"a\\\\b"')
        expect(escapePropertyAsHogQLIdentifier('end\\')).toEqual('"end\\\\"')
        // A backslash alongside a double quote takes the backtick branch and still escapes both.
        expect(escapePropertyAsHogQLIdentifier('a"\\b')).toEqual('`a"\\\\b`')
        // A backslash immediately before an inner backtick (which forces the backtick branch).
        expect(escapePropertyAsHogQLIdentifier('a"b\\`c')).toEqual('`a"b\\\\``c`')
    })

    it('escapes control characters instead of emitting them raw', () => {
        expect(escapePropertyAsHogQLIdentifier('a\tb')).toEqual('"a\\tb"')
        expect(escapePropertyAsHogQLIdentifier('a\nb')).toEqual('"a\\nb"')
        expect(escapePropertyAsHogQLIdentifier('a\bb')).toEqual('"a\\bb"')
        // An embedded double quote forces the backtick branch; the control char is still escaped.
        expect(escapePropertyAsHogQLIdentifier('a"\tb')).toEqual('`a"\\tb`')
    })
})

describe('escapeDottedHogQLIdentifier', () => {
    it('leaves simple dotted identifiers unquoted', () => {
        expect(escapeDottedHogQLIdentifier('demo.orders')).toEqual('demo.orders')
    })

    it('quotes each dotted segment independently when needed', () => {
        expect(escapeDottedHogQLIdentifier('demo.order items')).toEqual('demo."order items"')
    })
})
