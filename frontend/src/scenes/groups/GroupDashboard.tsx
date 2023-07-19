import { Dashboard } from 'scenes/dashboard/Dashboard'
import { DashboardPlacement, Group } from '~/types'

export function GroupDashboard({}: { groupData: Group; groupTypeName: string }): JSX.Element {
    return <Dashboard id={'4'} placement={DashboardPlacement.Group} />
}
