import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { CustomerProfileScope } from '~/types'

import { customerProfileLogic } from './customerProfileLogic'

jest.mock('lib/api')

describe('customerProfileLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.customerProfileConfigs, 'list').mockResolvedValue({ results: [] })
        jest.spyOn(api.externalDataSources, 'listSummaries').mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [{ source_type: 'Zendesk' }],
        } as any)
    })

    it('checks Zendesk availability using source summaries', async () => {
        const logic = customerProfileLogic({
            scope: CustomerProfileScope.PERSON,
            attrs: {},
            key: 'test-profile',
            canvasShortId: 'test-profile',
        })

        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadZendeskSourceSuccess']).toMatchValues({
            hasZendeskSource: true,
            hasZendeskSourceLoading: false,
        })

        expect(api.externalDataSources.listSummaries).toHaveBeenCalledTimes(1)
        expect(api.externalDataSources.list).not.toHaveBeenCalled()
        logic.unmount()
    })
})
