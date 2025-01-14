import { BindLogic, useActions, useValues } from 'kea'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { SceneExport } from 'scenes/sceneTypes'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID, llmObservabilityLogic } from './llmObservabilityLogic'

export const scene: SceneExport = {
    component: LLMObservabilityScene,
}

const Filters = (): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        shouldFilterTestAccounts,
    } = useValues(llmObservabilityLogic)
    const { setDates, setShouldFilterTestAccounts } = useActions(llmObservabilityLogic)

    return (
        <div className="flex justify-between items-center">
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            <TestAccountFilterSwitch checked={shouldFilterTestAccounts} onChange={setShouldFilterTestAccounts} />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(llmObservabilityLogic)

    return (
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 xxl:grid-cols-3 gap-4">
            {tiles.map(({ title, query }, i) => (
                <QueryCard
                    key={i}
                    title={title}
                    query={{ kind: NodeKind.InsightVizNode, source: query } as InsightVizNode}
                />
            ))}
        </div>
    )
}

export function LLMObservabilityScene(): JSX.Element {
    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID }}>
            <Filters />
            <Tiles />
        </BindLogic>
    )
}
