import { useValues } from 'kea'

import { capitalizeFirstLetter } from 'lib/utils'

import { Group } from '~/types'

import { GroupDashboardCard } from './cards/GroupDashboardCard'
import { GroupPeopleCard } from './cards/GroupPeopleCard'
import { GroupPropertiesCard } from './cards/GroupPropertiesCard'
import { groupLogic } from './groupLogic'

export function GroupOverview({ groupData }: { groupData: Group }): JSX.Element {
    const { groupTypeName } = useValues(groupLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="col-span-1">
                    <h2>{capitalizeFirstLetter(groupTypeName)} properties</h2>
                    <GroupPropertiesCard groupData={groupData} />
                </div>
                <div className="col-span-1">
                    <h2>Related people</h2>
                    <GroupPeopleCard groupData={groupData} />
                </div>
            </div>
            <GroupDashboardCard />
        </div>
    )
}
