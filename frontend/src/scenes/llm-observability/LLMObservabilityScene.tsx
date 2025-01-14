import { LemonBanner, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { SceneExport } from 'scenes/sceneTypes'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
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
    const { mobileLayout } = useValues(navigationLogic)

    return (
        <div
            className={clsx(
                'sticky flex justify-between items-center py-2 -mt-2 mb-2 bg-bg-3000 border-b z-20',
                mobileLayout ? 'top-[var(--breadcrumbs-height-full)]' : 'top-[var(--breadcrumbs-height-compact)]'
            )}
        >
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

const IngestionStatusCheck = (): JSX.Element | null => {
    const { hasSentAiGenerationEvent } = useValues(llmObservabilityLogic)
    if (hasSentAiGenerationEvent !== false) {
        return null
    }
    return (
        <LemonBanner type="warning" className="mt-2">
            <p>
                <strong>No LLM generation events have been detected!</strong>
            </p>
            <p>
                To use the LLM Observability product, please{' '}
                <Link to="https://posthog.com/docs/ai-engineering/observability">
                    instrument your LLM calls with the PostHog SDK
                </Link>{' '}
                (otherwise it'll be a little empty!)
            </p>
            <p>
                To get cost information, you'll also{' '}
                <Link to="/pipeline/new/transformation">need to enable the "AI Costs" transformation.</Link>
            </p>
        </LemonBanner>
    )
}

export function LLMObservabilityScene(): JSX.Element {
    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID }}>
            <IngestionStatusCheck />
            <Filters />
            <Tiles />
        </BindLogic>
    )
}
