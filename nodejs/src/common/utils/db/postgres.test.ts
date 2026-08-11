import { DependencyUnavailableError } from './error'
import { PostgresUse, handlePostgresError, isTransientPgError } from './postgres'

describe('transient postgres error classification', () => {
    test.each([
        ['connect ECONNREFUSED 10.0.0.1:6543', true],
        ['connect EHOSTUNREACH 10.0.0.1:6543', true],
        ['pooler is shutting down', true],
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
})
