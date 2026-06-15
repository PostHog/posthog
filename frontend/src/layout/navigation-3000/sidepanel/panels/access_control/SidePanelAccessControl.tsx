import { useValues } from 'kea'
import { useEffect } from 'react'

import { captureAccessControlEvent, resourceTypeToString } from 'lib/utils/accessControlUtils'

import { AccessControlResourceType } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { sidePanelContextLogic } from '../../sidePanelContextLogic'
import { AccessControlObject } from './AccessControlObject'

export const SidePanelAccessControl = (): JSX.Element => {
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)

    const { access_control_resource: resource, access_control_resource_id: resourceId } = sceneSidePanelContext

    useEffect(() => {
        if (!resource || !resourceId) {
            return
        }
        captureAccessControlEvent('access_control_side_panel_viewed', {
            resource,
            resource_id: resourceId,
        })
    }, [resource, resourceId])

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
