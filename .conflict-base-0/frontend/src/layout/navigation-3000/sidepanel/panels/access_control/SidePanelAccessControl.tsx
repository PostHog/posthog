import { useValues } from 'kea'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import { AccessControlObject } from './AccessControlObject'

export const SidePanelAccessControl = (): JSX.Element => {
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title="Access control" />
            <div className="flex-1 p-4 overflow-y-auto">
                {sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id ? (
                    <AccessControlObject
                        resource={sceneSidePanelContext.access_control_resource}
                        resource_id={sceneSidePanelContext.access_control_resource_id}
                        title="Object permissions"
                        description="Use object permissions to assign access for individuals and roles."
                    />
                ) : (
                    <p>Not supported</p>
                )}
            </div>
        </div>
    )
}
