import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { DebugSceneQuery } from 'scenes/debug/DebugSceneQuery'
import { SceneExport } from 'scenes/sceneTypes'

import { stringifiedExamples } from '~/queries/examples'

import { debugSceneLogic } from './debugSceneLogic'

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
                    <DebugSceneQuery query={query1} setQuery={setQuery1} queryKey="hogql-debug-1" />
                </div>
                {query2 ? (
                    <div className="flex-1 w-1/2">
                        <DebugSceneQuery query={query2} setQuery={setQuery2} queryKey="hogql-debug-2" />
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
