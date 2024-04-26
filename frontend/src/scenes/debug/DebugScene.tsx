import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { HogQLDebug } from 'scenes/debug/HogQLDebug'
import { Modifiers } from 'scenes/debug/Modifiers'
import { QueryTabs } from 'scenes/debug/QueryTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { stringifiedExamples } from '~/queries/examples'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { DataNode, HogQLQuery, Node } from '~/queries/schema'

import { debugSceneLogic } from './debugSceneLogic'

interface QueryDebugProps {
    queryKey: string
    query: string
    setQuery: (query: string) => void
}
function QueryDebug({ query, setQuery, queryKey }: QueryDebugProps): JSX.Element {
    let parsed: Record<string, any> | null = null
    try {
        parsed = JSON.parse(query)
    } catch (e) {
        // do nothing
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: (parsed ?? {}) as DataNode,
        key: queryKey,
        dataNodeCollectionId: queryKey,
    }
    const { response } = useValues(dataNodeLogic(dataNodeLogicProps))

    return (
        <>
            {parsed && parsed?.kind === 'HogQLQuery' ? (
                <HogQLDebug
                    queryKey={queryKey}
                    query={parsed as HogQLQuery}
                    setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                />
            ) : (
                <div className="space-y-4">
                    <QueryEditor
                        query={query}
                        setQuery={setQuery}
                        aboveButton={
                            <Modifiers
                                setQuery={
                                    parsed?.source
                                        ? (query) => setQuery(JSON.stringify({ ...parsed, source: query }, null, 2))
                                        : (query) => setQuery(JSON.stringify(query, null, 2))
                                }
                                query={parsed?.source ?? parsed}
                                response={response}
                            />
                        }
                    />
                    {parsed ? (
                        <QueryTabs
                            query={parsed as Node}
                            queryKey={queryKey}
                            response={response}
                            setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                        />
                    ) : null}
                </div>
            )}
        </>
    )
}

export function DebugScene(): JSX.Element {
    const { query1, query2 } = useValues(debugSceneLogic)
    const { setQuery1, setQuery2 } = useActions(debugSceneLogic)

    return (
        <div className="QueryScene">
            <PageHeader
                buttons={
                    <>
                        <LemonButton active={!!query2} onClick={() => (query2 ? setQuery2('') : setQuery2(query1))}>
                            Split
                        </LemonButton>
                        <LemonButton
                            active={query1 === stringifiedExamples.HogQLRaw}
                            onClick={() => setQuery1(stringifiedExamples.HogQLRaw)}
                        >
                            HogQL Debug
                        </LemonButton>
                        <LemonButton
                            active={query1 === stringifiedExamples.HogQLTable}
                            onClick={() => setQuery1(stringifiedExamples.HogQLTable)}
                        >
                            HogQL Table
                        </LemonButton>
                        <LemonButton
                            active={query1 === stringifiedExamples.Events}
                            onClick={() => setQuery1(stringifiedExamples.Events)}
                        >
                            Any Query
                        </LemonButton>
                        <LemonLabel>
                            <LemonSelect
                                placeholder="More sample queries"
                                options={Object.entries(stringifiedExamples)
                                    .filter(([k]) => k !== 'HogQLTable' && k !== 'HogQLRaw')
                                    .map(([k, v]) => {
                                        return { label: k, value: v }
                                    })}
                                onChange={(v) => {
                                    if (v) {
                                        setQuery1(v)
                                    }
                                }}
                            />
                        </LemonLabel>
                    </>
                }
            />
            <div className="flex gap-2">
                <div className="flex-1 w-1/2">
                    <QueryDebug query={query1} setQuery={setQuery1} queryKey="hogql-debug-1" />
                </div>
                {query2 ? (
                    <div className="flex-1 w-1/2">
                        <QueryDebug query={query2} setQuery={setQuery2} queryKey="hogql-debug-2" />
                    </div>
                ) : null}
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: DebugScene,
    logic: debugSceneLogic,
}
