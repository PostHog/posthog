import { useValues } from 'kea'

import { ActionInput } from './ActionInput'
import { ActionResults } from './ActionResults'
import { actionBarLogic } from './actionBarLogic'

export const ActionBar = (): JSX.Element => {
    const { activeFlow } = useValues(actionBarLogic)

    return (
        <div className="flex flex-col h-full">
            {(!activeFlow || activeFlow.instruction) && <ActionInput />}
            <ActionResults />
        </div>
    )
}
