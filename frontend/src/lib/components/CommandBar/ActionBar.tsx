import { useValues } from 'kea'

import { actionBarLogic } from './actionBarLogic'
import { ActionInput } from './ActionInput'
import { ActionResults } from './ActionResults'

export const ActionBar = (): JSX.Element => {
    const { activeFlow } = useValues(actionBarLogic)

    return (
        <div className="flex flex-col h-full">
            {(!activeFlow || activeFlow.instruction) && <ActionInput />}
            <ActionResults />
        </div>
    )
}
