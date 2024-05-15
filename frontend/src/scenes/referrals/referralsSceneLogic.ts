import { actions, kea, path } from 'kea'

import type { referralsSceneLogicType } from './referralsSceneLogicType'

export const referralsSceneLogic = kea<referralsSceneLogicType>([
    path(['scenes', 'referrals', 'referralsSceneLogic']),
    actions({}),
])
