import { MOCK_TEAM_ID } from 'lib/api.mock'

import { dayjs } from 'lib/dayjs'
import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AppContext, TeamType } from '~/types'

import { NodeKind } from './schema/schema-general'
import { hogql, setLatestVersionsOnQuery } from './utils'

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

describe('setLatestVersionsOnQuery', () => {
    it('handles circular references without stack overflow', () => {
        const parent: any = {
            kind: NodeKind.EventsQuery,
            name: 'parent',
            children: [],
        }
        const child: any = {
            kind: NodeKind.EventsNode,
            name: 'child',
            parent: parent,
        }
        parent.children.push(child)

        const result = setLatestVersionsOnQuery(parent)

        expect(result.name).toEqual('parent')
        expect(result.children).toHaveLength(1)
        expect(result.children[0].name).toEqual('child')
    })

    it('handles self-referencing objects', () => {
        const obj: any = {
            kind: NodeKind.HogQLQuery,
            name: 'self',
        }
        obj.self = obj

        const result = setLatestVersionsOnQuery(obj)

        expect(result.name).toEqual('self')
    })

    it('handles deeply nested circular references', () => {
        const root: any = {
            kind: NodeKind.EventsQuery,
            level: 'root',
        }
        const nested: any = {
            kind: NodeKind.EventsNode,
            level: 'nested',
            parent: root,
        }
        const deepNested: any = {
            kind: NodeKind.HogQuery,
            level: 'deep',
            parent: nested,
            root: root,
        }
        root.child = nested
        nested.child = deepNested

        const result = setLatestVersionsOnQuery(root)

        expect(result.level).toEqual('root')
        expect(result.child.level).toEqual('nested')
        expect(result.child.child.level).toEqual('deep')
    })
})
