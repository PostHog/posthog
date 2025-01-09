import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SceneExport } from 'scenes/sceneTypes'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID, llmObservabilityLogic } from './llmObservabilityLogic'

export const scene: SceneExport = {
    component: LLMObservabilityScene,
}

const Filters = (): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
    } = useValues(llmObservabilityLogic)
    const { setDates } = useActions(llmObservabilityLogic)
    const { mobileLayout } = useValues(navigationLogic)

    return (
        <div
            className={clsx(
                'sticky z-20 bg-bg-3000',
                mobileLayout ? 'top-[var(--breadcrumbs-height-full)]' : 'top-[var(--breadcrumbs-height-compact)]'
            )}
        >
            <div className="border-b py-2 flex flex-row flex-wrap gap-2 md:[&>*]:grow-0 [&>*]:grow">
                <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            </div>
        </div>
    )
}

export function LLMObservabilityScene(): JSX.Element {
    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID }}>
            <Filters />
        </BindLogic>
    )
}
