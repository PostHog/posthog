import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountSqlQueryLogic } from './accountSqlQueryLogic'

describe('accountSqlQueryLogic', () => {
    const props = {
        accountId: 'account-one',
        externalId: 'org-one',
        instanceId: 'first-tile',
        query: 'select * from engagements where org_id = {account_external_id}',
    }

    beforeEach(() => initKeaTests())

    it('keeps two tiles independent when one changes to an invalid query', async () => {
        const first = accountSqlQueryLogic(props)
        const second = accountSqlQueryLogic({ ...props, instanceId: 'second-tile' })
        await expectLogic(first, () => {
            first.mount()
        }).toFinishAllListeners()
        await expectLogic(second, () => {
            second.mount()
        }).toFinishAllListeners()
        expect(first.values.queryNode).not.toBeNull()
        expect(second.values.queryNode).not.toBeNull()

        await expectLogic(first, () => {
            accountSqlQueryLogic({ ...props, query: 'select * from engagements' })
        }).toFinishAllListeners()

        expect(first.values.queryNode).toBeNull()
        expect(second.values.queryNode?.source).toMatchObject({ query: props.query })
    })

    it('discards an earlier parse when the query changes before it finishes', async () => {
        const logic = accountSqlQueryLogic(props)
        await expectLogic(logic, () => {
            logic.mount()
            accountSqlQueryLogic({ ...props, query: 'select * from engagements' })
        }).toFinishAllListeners()

        expect(logic.values.queryNode).toBeNull()
        expect(logic.values.queryNodeLoading).toBe(false)
    })

    it('reloads equal SQL on a different source without changing another tile', async () => {
        const connectionId = '11111111-1111-4111-8111-111111111111'
        const first = accountSqlQueryLogic(props)
        const second = accountSqlQueryLogic({ ...props, instanceId: 'second-tile' })
        await expectLogic(first, () => {
            first.mount()
        }).toFinishAllListeners()
        await expectLogic(second, () => {
            second.mount()
        }).toFinishAllListeners()

        await expectLogic(first, () => {
            accountSqlQueryLogic({ ...props, connectionId })
        }).toFinishAllListeners()
        expect(first.values.queryNode?.source).toMatchObject({
            connectionId,
            query: props.query,
            values: { account_external_id: props.externalId },
        })
        expect(second.values.queryNode?.source).not.toHaveProperty('connectionId')

        await expectLogic(first, () => {
            accountSqlQueryLogic({ ...props, connectionId: undefined })
        }).toFinishAllListeners()
        expect(first.values.queryNode?.source).not.toHaveProperty('connectionId')
    })

    it('discards a pending source when the saved connection becomes invalid', async () => {
        const logic = accountSqlQueryLogic(props)
        await expectLogic(logic, () => {
            logic.mount()
            accountSqlQueryLogic({ ...props, connectionId: 123 })
        }).toFinishAllListeners()
        expect(logic.values.queryNode).toBeNull()
    })
})
