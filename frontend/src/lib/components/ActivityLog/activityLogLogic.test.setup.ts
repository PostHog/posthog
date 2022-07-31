import {
    ActivityChange,
    ActivityLogItem,
    ActivityScope,
    Describer,
    PersonMerge,
} from 'lib/components/ActivityLog/humanizeActivity'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { expectLogic } from 'kea-test-utils'

export interface APIMockSetup {
    name: string
    activity: string
    changes?: ActivityChange[] | null
    scope: ActivityScope
    merge?: PersonMerge | null
}

export const makeAPIItem = ({
    name,
    activity,
    changes = null,
    scope,
    merge = null,
}: APIMockSetup): ActivityLogItem => ({
    user: { first_name: 'peter', email: 'peter@posthog.com' },
    activity,
    scope,
    item_id: '7',
    detail: {
        changes,
        merge,
        name,
    },
    created_at: '2022-02-05T16:28:39.594Z',
})

export async function testSetup(
    activityLogItem: ActivityLogItem,
    scope: ActivityScope,
    describer: Describer,
    url: string
): Promise<ReturnType<typeof activityLogLogic.build>> {
    useMocks({
        get: {
            [url]: {
                results: [activityLogItem],
            },
        },
    })
    initKeaTests()
    const logic = activityLogLogic({ scope, id: 7, describer })
    logic.mount()

    await expectLogic(logic).toFinishAllListeners()
    return logic
}

export const makeTestSetup = (scope: ActivityScope, describer: Describer, url: string) => {
    return async (
        name: string,
        activity: string,
        changes: ActivityChange[] | null,
        merge?: PersonMerge
    ): Promise<ReturnType<typeof activityLogLogic.build>> => {
        return await testSetup(makeAPIItem({ scope, name, activity, changes, merge }), scope, describer, url)
    }
}
