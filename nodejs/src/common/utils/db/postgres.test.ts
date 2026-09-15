import { DependencyUnavailableError } from './error'
import { PostgresUse, handlePostgresError, isTransientPgError, postgresErrorFingerprint } from './postgres'

describe('postgres error classification', () => {
    test.each([
        ['connect ECONNREFUSED 10.0.0.1:6543', true],
        ['connect EHOSTUNREACH 10.0.0.1:6543', true],
        ['pooler is shutting down', true],
        ['Cannot use a pool after calling end on the pool', true],
        ['server conn crashed?', true],
        ['duplicate key value violates unique constraint', false],
        ['syntax error at or near "SELCT"', false],
    ])('isTransientPgError(%s) -> %s', (message, expected) => {
        expect(isTransientPgError(new Error(message))).toBe(expected)
    })

    test.each([undefined, null, 'a plain string', new Error()])('isTransientPgError(%p) -> false', (value) => {
        expect(isTransientPgError(value)).toBe(false)
    })

    it('wraps transient errors in a retriable DependencyUnavailableError', () => {
        expect(() => handlePostgresError(new Error('pooler is shutting down'), PostgresUse.PERSONS_WRITE)).toThrow(
            expect.objectContaining({ name: 'DependencyUnavailableError', isRetriable: true })
        )
    })

    it('does nothing for non-transient errors', () => {
        expect(() =>
            handlePostgresError(new Error('duplicate key value violates unique constraint'), PostgresUse.PERSONS_WRITE)
        ).not.toThrow(DependencyUnavailableError)
    })

    describe('postgresErrorFingerprint', () => {
        const pgError = (code: string, message: string, constraint?: string): Error =>
            Object.assign(new Error(message), { code, constraint })

        it('gives every class of database failure a key of its own', () => {
            // One error tracking issue absorbed all of these, because the
            // driver throws them all from the same frames.
            const keys = [
                pgError('40P01', 'deadlock detected'),
                pgError('23503', 'insert violates foreign key', 'posthog_person_team_id_fkey'),
                pgError('23503', 'insert violates foreign key', 'posthog_persondistinctid_person_id_fkey'),
                pgError('22001', 'value too long for type character varying(400)'),
                // The pooler stamps both of these with SQLSTATE 08P01, so only
                // the message separates pool saturation from a dead backend.
                pgError('08P01', 'query_wait_timeout'),
                pgError('08P01', 'server conn crashed?'),
                new Error('server closed the connection unexpectedly'),
            ].map((error) => postgresErrorFingerprint('scope', error))

            expect(new Set(keys).size).toBe(keys.length)
        })

        it('reads the code through the wrapper a transient failure is rethrown in', () => {
            const cause = pgError('40P01', 'deadlock detected')

            expect(
                postgresErrorFingerprint('scope', new DependencyUnavailableError('boom', 'Postgres', cause))
            ).toEqual(postgresErrorFingerprint('scope', cause))
        })

        it('leaves an error of our own to its stack', () => {
            expect(postgresErrorFingerprint('scope', new TypeError('cannot read x of undefined'))).toBeUndefined()
        })
    })
})
