import './HedgehogBuddy.scss'

import { useActions, useValues } from 'kea'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { HedgehogBuddy } from './HedgehogBuddy'
import { hedgehogBuddyLogic } from './hedgehogBuddyLogic'

export function HedgehogBuddyWithLogic(): JSX.Element {
    const { hedgehogModeEnabled } = useValues(hedgehogBuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogBuddyLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return hedgehogModeEnabled ? (
        <HedgehogBuddy onClose={() => setHedgehogModeEnabled(false)} isDarkModeOn={isDarkModeOn} />
    ) : (
        <></>
    )
}
