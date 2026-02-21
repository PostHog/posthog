import { useValues } from 'kea'

import { resourceTypeToString } from 'lib/utils/accessControlUtils'

import { AccessControlResourceType } from '~/types'

import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import { AccessControlObject } from './AccessControlObject'

export const SidePanelAccessControl = (): JSX.Element => {
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)

    return (
        <div className="flex flex-col overflow-hidden grow">
            <SidePanelContentContainer>
                <SidePanelPaneHeader title="Access control" />
                {sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id ? (
                    <div className="px-1">
                        <AccessControlObject
                            resource={sceneSidePanelContext.access_control_resource}
                            resource_id={sceneSidePanelContext.access_control_resource_id}
                            title="Object permissions"
                            description={`Use object permissions to assign access for individuals and roles to this ${resourceTypeToString(sceneSidePanelContext.access_control_resource as AccessControlResourceType)}.`}
                        />
                    </div>
                ) : (
                    <p>Not supported</p>
                )}
            </SidePanelContentContainer>
        </div>
    )
}
