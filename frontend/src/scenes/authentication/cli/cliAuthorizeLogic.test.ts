import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { AGENT_USE_CASE_SCOPES } from './agentScopes.generated'
import { cliAuthorizeLogic } from './cliAuthorizeLogic'

describe('cliAuthorizeLogic', () => {
    let logic: ReturnType<typeof cliAuthorizeLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = cliAuthorizeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('grants the MCP scope set for the agent use case, minus key-disabled writes', async () => {
        router.actions.push('/cli/authorize', { code: 'ABCD-1234', use_cases: 'agent' })

        await expectLogic(logic).toMatchValues({
            requestedUseCases: ['agent'],
        })
        const scopes = logic.values.authorize.scopes
        // Covers the agent surface (reads + the writes that are allowed on a key)
        expect(scopes).toEqual(expect.arrayContaining(['user:read', 'project:read', 'query:read', 'insight:write']))
        // But drops writes the product withholds from manually-created keys
        expect(scopes).not.toContain('file_system:write')
        expect(scopes).not.toContain('integration:write')
        expect(scopes).not.toContain('user:write')
        // Faithful subset of the generated MCP mirror
        expect(scopes.every((scope) => (AGENT_USE_CASE_SCOPES as readonly string[]).includes(scope))).toBe(true)
    })

    it('filters out unknown use cases from the URL', async () => {
        router.actions.push('/cli/authorize', { code: 'ABCD-1234', use_cases: 'agent,bogus,schema' })

        await expectLogic(logic).toMatchValues({
            requestedUseCases: ['agent', 'schema'],
        })
    })

    it('defaults to the agent use case when none are specified', async () => {
        router.actions.push('/cli/authorize', { code: 'ABCD-1234' })

        await expectLogic(logic).toMatchValues({
            requestedUseCases: ['agent'],
        })
        expect(logic.values.authorize.scopes).toEqual(
            expect.arrayContaining(['user:read', 'project:read', 'query:read'])
        )
        expect(logic.values.authorize.scopes).not.toContain('file_system:write')
    })
})
