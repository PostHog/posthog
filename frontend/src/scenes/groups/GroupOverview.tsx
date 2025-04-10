import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { Group } from '~/types'

import { GroupPeopleCard } from './cards/GroupPeopleCard'
import { GroupPropertiesCard } from './cards/GroupPropertiesCard'

export function GroupOverview({ groupData }: { groupData: Group }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="col-span-1">
                    <h2>Properties</h2>
                    <GroupPropertiesCard groupData={groupData} />
                </div>
                <div className="col-span-1">
                    <h2>People</h2>
                    <GroupPeopleCard groupData={groupData} />
                </div>
            </div>
            <div>
                <h2>Engagement</h2>
                <div className="h-64">
                    <Query
                        query={{
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                dateRange: {
                                    date_from: '-90d',
                                },
                                series: [
                                    {
                                        kind: NodeKind.EventsNode,
                                        math: 'total',
                                        event: null,
                                    },
                                    {
                                        kind: NodeKind.EventsNode,
                                        math: 'dau',
                                        event: null,
                                    },
                                ],
                            },
                            embedded: true,
                        }}
                        context={{ refresh: 'force_blocking' }}
                    />
                </div>
            </div>
        </div>
    )
}
