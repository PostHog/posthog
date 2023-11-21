import { useActions, useValues } from 'kea'
import { hedgehogbuddyLogic } from './hedgehogbuddyLogic'
import './HedgehogBuddy.scss'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { HedgehogBuddy } from './HedgehogBuddy'

export function HedgehogBuddyWithLogic(): JSX.Element {
    const { hedgehogModeEnabled } = useValues(hedgehogbuddyLogic)
    const { setHedgehogModeEnabled } = useActions(hedgehogbuddyLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return hedgehogModeEnabled ? (
        <HedgehogBuddy onClose={() => setHedgehogModeEnabled(false)} isDarkModeOn={isDarkModeOn} />
    ) : (
        <></>
    )
}
