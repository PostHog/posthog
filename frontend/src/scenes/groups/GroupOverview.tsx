import { useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { Group } from '~/types'

import { GroupDashboardCard } from './cards/GroupDashboardCard'
import { GroupNotebookCard } from './cards/GroupNotebookCard'
import { GroupPeopleCard } from './cards/GroupPeopleCard'
import { GroupPropertiesCard } from './cards/GroupPropertiesCard'
import { groupLogic } from './groupLogic'

export function GroupOverview({ groupData }: { groupData: Group }): JSX.Element {
    const { groupTypeName } = useValues(groupLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.CRM_ITERATION_ONE]) {
        return (
            <div className="flex flex-col gap-4">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
                    <div className="col-span-1 order-1">
                        <GroupNotebookCard />
                    </div>
                    <div className="col-span-1 flex flex-col gap-4 order-2">
                        <div>
                            <h2>{capitalizeFirstLetter(groupTypeName)} properties</h2>
                            <GroupPropertiesCard groupData={groupData} />
                        </div>
                        <div>
                            <h2>Related people</h2>
                            <GroupPeopleCard groupData={groupData} />
                        </div>
                    </div>
                </div>
                <div>
                    <h2>Insights</h2>
                    <GroupDashboardCard />
                </div>
            </div>
        )
    }

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
            <div>
                <h2>Insights</h2>
                <GroupDashboardCard />
            </div>
        </div>
    )
}
