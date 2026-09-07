import { z } from 'zod'

import { getUserStoragePrefix } from 'lib/logic/persistence'
import { localStorageSlot } from 'lib/utils/localStorageSlot'

// Test account filters are defined per environment, so this preference is scoped to the user and
// the team like every other persisted preference. An unscoped key followed the browser into every
// other project and hid the data there too, which reads as data loss rather than as a filter
export const filterTestAccountsDefaultStorage = localStorageSlot(
    () => `${getUserStoragePrefix()}default_filter_test_accounts`,
    z.boolean()
)
