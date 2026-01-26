import { useValues } from 'kea'

import { resourceTypeToString } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'

import { AccessControlResourceType } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import { AccessControlObject } from './AccessControlObject'

export const SidePanelAccessControl = ({ isScenePanel }: { isScenePanel?: boolean }): JSX.Element => {
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)

    return (
        <div className="flex flex-col overflow-hidden">
            {isScenePanel ? null : <SidePanelPaneHeader title="Access control" />}
            <div className={cn('flex-1 overflow-y-auto', isScenePanel ? 'px-1' : 'p-4')}>
                {sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id ? (
                    <AccessControlObject
                        resource={sceneSidePanelContext.access_control_resource}
                        resource_id={sceneSidePanelContext.access_control_resource_id}
                        title="Object permissions"
                        description={`Use object permissions to assign access for individuals and roles to this ${resourceTypeToString(sceneSidePanelContext.access_control_resource as AccessControlResourceType)}.`}
                    />
                ) : (
                    <p>Not supported</p>
                )}
            </div>
        </div>
    )
}
