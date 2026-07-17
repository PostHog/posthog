import { SessionMap, SessionSet } from './session-map'

describe('session-map', () => {
    describe('SessionMap', () => {
        it('looks a value up by a freshly-built (teamId, sessionId) pair', () => {
            const map = new SessionMap<string>()
            map.set(1, 'a', 'x')

            // A different call site builds a new pair — a plain Map keyed by object would miss this.
            expect(map.get(1, 'a')).toBe('x')
        })

        it('scopes by team, so the same session id under another team is distinct', () => {
            const map = new SessionMap<string>()
            map.set(1, 'shared', 'one')
            map.set(2, 'shared', 'two')

            expect(map.get(1, 'shared')).toBe('one')
            expect(map.get(2, 'shared')).toBe('two')
            expect(map.size).toBe(2)
        })

        it('returns undefined for an absent pair and supports has/delete', () => {
            const map = new SessionMap<string>()
            map.set(1, 'a', 'x')

            expect(map.get(1, 'b')).toBeUndefined()
            expect(map.has(1, 'a')).toBe(true)
            expect(map.delete(1, 'a')).toBe(true)
            expect(map.has(1, 'a')).toBe(false)
            expect(map.size).toBe(0)
        })
    })

    describe('SessionSet', () => {
        it('dedupes repeated pairs and iterates the distinct ones', () => {
            const set = new SessionSet()
            set.add(1, 'a').add(1, 'a').add(2, 'a')

            expect(set.size).toBe(2)
            expect([...set]).toEqual([
                { teamId: 1, sessionId: 'a' },
                { teamId: 2, sessionId: 'a' },
            ])
        })
    })
})
