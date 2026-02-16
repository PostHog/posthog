import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { resourceTypeToString } from 'lib/utils/accessControlUtils'
import { cn } from 'lib/utils/css-classes'

import { AccessControlResourceType } from '~/types'

import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import { AccessControlObject } from './AccessControlObject'

export const SidePanelAccessControl = (): JSX.Element => {
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    return (
        <div className="flex flex-col overflow-hidden grow">
            {!isRemovingSidePanelFlag ? <SidePanelPaneHeader title="Access control" /> : null}
            <SidePanelContentContainer flagOffClassName="flex-1 p-4 overflow-y-auto">
                {isRemovingSidePanelFlag ? <SidePanelPaneHeader title="Access control" /> : null}
                {sceneSidePanelContext.access_control_resource && sceneSidePanelContext.access_control_resource_id ? (
                    <div
                        className={cn({
                            'px-1': isRemovingSidePanelFlag,
                            contents: !isRemovingSidePanelFlag,
                        })}
                    >
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
