import { useMountedLogic } from 'kea'

import { actionBarLogic } from './actionBarLogic'

import ActionInput from './ActionInput'
import ActionResults from './ActionResults'
import ActionTabs from './ActionTabs'

const ActionBar = (): JSX.Element => {
    useMountedLogic(actionBarLogic)

    return (
        <div className="flex flex-col h-full">
            <ActionInput />
            <ActionResults />
            <ActionTabs />
        </div>
    )
}

export default ActionBar
