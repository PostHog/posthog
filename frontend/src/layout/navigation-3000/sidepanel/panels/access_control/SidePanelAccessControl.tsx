import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { AccessControlObject } from './AccessControlObject'

export const SidePanelAccessControl = (): JSX.Element => {
    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title="Access control" />
            <div className="flex-1 p-4 overflow-y-auto">
                <AccessControlObject resource="project" />
            </div>
        </div>
    )
}
