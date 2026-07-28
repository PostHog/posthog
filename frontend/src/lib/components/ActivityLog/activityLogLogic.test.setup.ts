import { expectLogic } from 'kea-test-utils'

import { activityLogLogic, ensureActivityDescribersLoaded } from 'lib/components/ActivityLog/activityLogLogic'
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
    // eslint-disable-next-line react-hooks/rules-of-hooks -- useMocks is an MSW test helper, not a React hook
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
    // `fetchActivity` awaits the code-split describer registry, so without this hook whichever test
    // calls the returned setup first has to transpile and require every product's describers inside
    // its own timeout. That is several seconds of one-time work against jest's 5s default, which
    // leaves so little headroom that a contended CI shard tips the first test into a timeout.
    // The hook gets an explicit timeout because a cold transform cache can be slower still.
    beforeAll(async () => {
        await ensureActivityDescribersLoaded()
    }, 60_000)

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
