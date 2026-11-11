import { useValues } from 'kea'
import { useEffect } from 'react'

import { IconLock } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { captureAccessControlEvent, resourceTypeToString } from 'lib/utils/accessControlUtils'

import { AccessControlResourceType } from '~/types'

import { sidePanelContextLogic } from '../../../sidePanelContextLogic'
import { QuillAccessControlObject } from './QuillAccessControlObject'

export function QuillAccessControlPanel(): JSX.Element {
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)
    const { access_control_resource: resource, access_control_resource_id: resourceId } = sceneSidePanelContext

    useEffect(() => {
        if (!resource || !resourceId) {
            return
        }
        // pinned: analytics event name, shared with the flag-off panel
        captureAccessControlEvent('access_control_side_panel_viewed', {
            resource,
            resource_id: resourceId,
        })
    }, [resource, resourceId])

    if (!resource || !resourceId) {
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconLock />
                    </EmptyMedia>
                    <EmptyTitle>Access control isn't available here</EmptyTitle>
                    <EmptyDescription>
                        Open a dashboard, insight, or another saved object to manage who can access it.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4">
            <div className="flex flex-col p-4">
                <QuillAccessControlObject
                    resource={resource}
                    resource_id={resourceId}
                    title="Object permissions"
                    description={`Use object permissions to assign access for individuals and roles to this ${resourceTypeToString(resource as AccessControlResourceType)}.`}
                />
            </div>
        </div>
    )
}
