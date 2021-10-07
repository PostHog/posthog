import { mockAPI } from 'lib/api.mock'
import { initKeaTestLogic } from '~/test/kea-test-utils'
import { insightLogic } from './insightLogic'

jest.mock('lib/api')

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    it('requires props', () => {
        expect(() => {
            insightLogic()
        }).toThrow('Must init with dashboardItemId, even if undefined')
    })

    describe('when there is no props id', () => {
        initKeaTestLogic({
            logic: insightLogic,
            props: {
                dashboardItemId: undefined,
            },
            onLogic: (l) => (logic = l),
        })

        it('has the key set to "new"', () => {
            expect(logic.key).toEqual('new')
        })
    })

    describe('when there is a prop id', () => {
        initKeaTestLogic({
            logic: insightLogic,
            props: {
                dashboardItemId: 42,
            },
            onLogic: (l) => (logic = l),
        })

        it('has the key set to the id', () => {
            expect(logic.key).toEqual(42)
        })
    })
})
