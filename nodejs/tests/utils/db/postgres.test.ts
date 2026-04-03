import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { PostgresUse, handlePostgresError } from '../../../src/utils/db/postgres'

describe('handlePostgresError', () => {
    it.each([
        ['connection to server at "pg:5432" refused'],
        ['could not translate host name "pg" to address'],
        ['server conn crashed'],
        ['no more connections allowed (max_client_conn)'],
        ['server closed the connection unexpectedly'],
        ['getaddrinfo EAI_AGAIN pg'],
        ['Connection terminated unexpectedly'],
        ['connect ECONNREFUSED 127.0.0.1:5432'],
        ['connect ETIMEDOUT 10.0.0.1:5432'],
        ['query_wait_timeout'],
        ['server login has been failing, try again later (server_login_retry)'],
    ])('throws retriable DependencyUnavailableError for "%s"', (message) => {
        try {
            handlePostgresError(new Error(message), PostgresUse.COMMON_WRITE)
            fail('expected to throw')
        } catch (e) {
            expect(e).toBeInstanceOf(DependencyUnavailableError)
            expect((e as DependencyUnavailableError).isRetriable).toBe(true)
        }
    })

    it.each([
        ['duplicate key value violates unique constraint'],
        ['relation "table" does not exist'],
        ['syntax error at or near "SELECT"'],
    ])('does not throw for non-transient error "%s"', (message) => {
        expect(() => handlePostgresError(new Error(message), PostgresUse.COMMON_WRITE)).not.toThrow()
    })
})
