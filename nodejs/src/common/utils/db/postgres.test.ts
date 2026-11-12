import { DatabaseError } from 'pg'

import { DependencyUnavailableError } from './error'
import { PostgresUse, handlePostgresError, isTransientPgError } from './postgres'

describe('transient postgres error classification', () => {
    test.each([
        ['connect ECONNREFUSED 10.0.0.1:6543', true],
        ['connect EHOSTUNREACH 10.0.0.1:6543', true],
        ['pooler is shutting down', true],
        ['Cannot use a pool after calling end on the pool', true],
        ['server conn crashed?', true],
        ['timeout exceeded when trying to connect', true],
        ['Connection terminated due to connection timeout', true],
        ['duplicate key value violates unique constraint', false],
        ['syntax error at or near "SELCT"', false],
    ])('isTransientPgError(%s) -> %s', (message, expected) => {
        expect(isTransientPgError(new Error(message))).toBe(expected)
    })

    test.each([
        ['53300', 'sorry, too many clients already', true],
        ['57P01', 'terminating connection due to administrator command', true],
        ['57P02', 'terminating connection because of crash of another server process', true],
        ['57P03', 'the database system is starting up', true],
        ['57P03', 'the database system is shutting down', true],
        ['57014', 'canceling statement due to statement timeout', false],
        ['23505', 'duplicate key value violates unique constraint', false],
    ])('isTransientPgError(SQLSTATE %s: %s) -> %s', (code, message, expected) => {
        const error = new DatabaseError(message, message.length, 'error')
        error.code = code
        expect(isTransientPgError(error)).toBe(expected)
    })

    test.each([undefined, null, 'a plain string', new Error()])('isTransientPgError(%p) -> false', (value) => {
        expect(isTransientPgError(value)).toBe(false)
    })

    it('wraps transient errors in a retriable DependencyUnavailableError', () => {
        expect(() => handlePostgresError(new Error('pooler is shutting down'), PostgresUse.PERSONS_WRITE)).toThrow(
            expect.objectContaining({ name: 'DependencyUnavailableError', isRetriable: true })
        )
    })

    it('wraps a transient SQLSTATE in a retriable DependencyUnavailableError', () => {
        const error = new DatabaseError('the database system is starting up', 0, 'error')
        error.code = '57P03'
        expect(() => handlePostgresError(error, PostgresUse.COMMON_WRITE)).toThrow(
            expect.objectContaining({ name: 'DependencyUnavailableError', isRetriable: true })
        )
    })

    it('does nothing for non-transient errors', () => {
        expect(() =>
            handlePostgresError(new Error('duplicate key value violates unique constraint'), PostgresUse.PERSONS_WRITE)
        ).not.toThrow(DependencyUnavailableError)
    })
})
