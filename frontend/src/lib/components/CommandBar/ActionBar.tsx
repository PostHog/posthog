import { useValues } from 'kea'

import { actionBarLogic } from './actionBarLogic'

import ActionInput from './ActionInput'
import ActionResults from './ActionResults'
import ActionTabs from './ActionTabs'

const ActionBar = (): JSX.Element => {
    const { activeFlow } = useValues(actionBarLogic)

    return (
        <div className="flex flex-col h-full">
            {(!activeFlow || activeFlow.instruction) && <ActionInput />}
            {<ActionResults />}
            <ActionTabs />
        </div>
    )
}

export default ActionBar
