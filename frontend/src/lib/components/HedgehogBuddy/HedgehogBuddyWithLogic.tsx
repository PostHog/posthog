import './HedgehogBuddy.scss'

import { useActions, useValues } from 'kea'

import { HedgehogBuddy, MyHedgehogBuddy } from './HedgehogBuddy'
import { hedgehogBuddyLogic } from './hedgehogBuddyLogic'

export function HedgehogBuddyWithLogic(): JSX.Element {
    const { hedgehogModeEnabled } = useValues(hedgehogBuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogBuddyLogic)

    return hedgehogModeEnabled ? (
        <>
            <MyHedgehogBuddy onClose={() => setHedgehogModeEnabled(false)} />

            <HedgehogBuddy />
        </>
    ) : (
        <></>
    )
}
