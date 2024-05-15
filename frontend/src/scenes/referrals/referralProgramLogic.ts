import { actions, kea, path, props } from 'kea'

import { ReferralProgram } from '~/types'

import type { referralProgramLogicType } from './referralProgramLogicType'

export interface ReferralProgramLogicProps {
    referralProgram: ReferralProgram
}

export const referralProgramLogic = kea<referralProgramLogicType>([
    path(['scenes', 'referrals', 'referralProgramLogic']),
    props({} as ReferralProgramLogicProps),
    actions({}),
])
