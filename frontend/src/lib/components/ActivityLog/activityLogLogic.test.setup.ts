import { expectLogic } from 'kea-test-utils'

import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityChange, ActivityLogItem, PersonMerge, Trigger } from 'lib/components/ActivityLog/humanizeActivity'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

interface APIMockSetup {
    name: string
    activity: string
    changes?: ActivityChange[] | null
    scope: ActivityScope
    merge?: PersonMerge | null
    trigger?: Trigger | null
}

const makeAPIItem = ({
    name,
    activity,
    changes = null,
    scope,
    merge = null,
    trigger = null,
}: APIMockSetup): ActivityLogItem => ({
    user: { first_name: 'peter', email: 'peter@posthog.com' },
    activity,
    scope,
    item_id: '7',
    detail: {
        changes,
        merge,
        name,
        trigger,
    },
    created_at: '2022-02-05T16:28:39.594Z',
})

// oxlint-disable-next-line react-hooks/rules-of-hooks
async function testSetup(
    activityLogItem: ActivityLogItem,
    scope: ActivityScope,
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
    const logic = activityLogLogic({ scope, id: 7 })
    logic.mount()

    await expectLogic(logic).toFinishAllListeners()
    return logic
}

export const makeTestSetup = (scope: ActivityScope, url: string) => {
    return async (
        name: string,
        activity: string,
        changes: ActivityChange[] | null,
        merge?: PersonMerge | null,
        trigger?: Trigger | null
    ): Promise<ReturnType<typeof activityLogLogic.build>> => {
        const activityLogItem = makeAPIItem({ scope, name, activity, changes, merge, trigger })
        return await testSetup(activityLogItem, scope, url)
    }
}
