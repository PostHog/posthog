import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { AccessControlObject } from './AccessControlObject'

export const SidePanelAccessControl = (): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)

    if (!currentTeam) {
        return <Spinner />
    }

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title="Access control" />
            <div className="flex-1 p-4 overflow-y-auto">
                <AccessControlObject resource="project" resource_id={`${currentTeam.id}`} />
            </div>
        </div>
    )
}
