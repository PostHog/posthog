import { useValues } from 'kea'

import { actionBarLogic } from './actionBarLogic'

import ActionInput from './ActionInput'
import ActionResults from './ActionResults'

const ActionBar = (): JSX.Element => {
    const { activeFlow } = useValues(actionBarLogic)

    return (
        <div className="flex flex-col h-full">
            {(!activeFlow || activeFlow.instruction) && <ActionInput />}
            {<ActionResults />}
        </div>
    )
}

export default ActionBar
