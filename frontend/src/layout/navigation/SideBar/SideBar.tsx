import { ActivationSidebar } from 'lib/components/ActivationSidebar/ActivationSidebar'
import { DebugNotice } from 'lib/components/DebugNotice'

export function SideBar(): JSX.Element {
    return (
        <div>
            <DebugNotice />
            <ActivationSidebar />
        </div>
    )
}
