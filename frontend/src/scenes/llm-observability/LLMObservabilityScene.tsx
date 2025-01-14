import clsx from 'clsx'
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
        <div className="mb-4 flex justify-between items-center">
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            <TestAccountFilterSwitch checked={shouldFilterTestAccounts} onChange={setShouldFilterTestAccounts} />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(llmObservabilityLogic)

    return (
        <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-6 gap-4">
            {tiles.map(({ title, description, query }, i) => (
                <QueryCard
                    key={i}
                    title={title}
                    description={description}
                    query={{ kind: NodeKind.InsightVizNode, source: query } as InsightVizNode}
                    className={clsx('h-96', i < 3 || i >= 5 ? 'xl:col-span-2' : 'xl:col-span-3')}
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
