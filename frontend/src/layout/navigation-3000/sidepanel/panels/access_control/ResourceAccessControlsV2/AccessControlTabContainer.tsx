import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AvailableFeature } from '~/types'

import type { AccessControlsTab } from './types'

export function AccessControlTabContainer(props: {
    activeTab: AccessControlsTab
    children?: React.ReactNode
}): JSX.Element {
    if (props.activeTab === 'roles') {
        return (
            <PayGateMini feature={AvailableFeature.ROLE_BASED_ACCESS} featureDetail="resource-access-controls-roles">
                <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="access-control-roles">
                    {props.children}
                </PayGateMini>
            </PayGateMini>
        )
    }
    if (props.activeTab === 'members') {
        return (
            <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="access-control-members">
                {props.children}
            </PayGateMini>
        )
    }

    return <>{props.children}</>
}
