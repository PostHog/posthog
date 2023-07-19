import { DashboardPlacement, PersonType } from '~/types'
import { Dashboard } from 'scenes/dashboard/Dashboard'

export function PersonDashboard({}: { person: PersonType }): JSX.Element {
    return <Dashboard id={'4'} placement={DashboardPlacement.Person} />
}
