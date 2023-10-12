import { debugSceneLogic } from './debugSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { stringifiedExamples } from '~/queries/examples'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HogQLQuery } from '~/queries/schema'
import { HogQLDebug } from 'scenes/debug/HogQLDebug'

export function DebugScene(): JSX.Element {
    const { query } = useValues(debugSceneLogic)
    const { setQuery } = useActions(debugSceneLogic)

    let parsed: Record<string, any> | undefined
    try {
        parsed = JSON.parse(query)
    } catch (e) {
        // do nothing
    }

    const showQueryEditor = !(
        parsed &&
        parsed.kind == 'DataTableNode' &&
        parsed.source.kind == 'HogQLQuery' &&
        (parsed.full || parsed.showHogQLEditor)
    )

    return (
        <div className="QueryScene">
            <PageHeader
                title="Query Debugger"
                buttons={
                    <>
                        <LemonButton
                            active={query === stringifiedExamples.HogQLRaw}
                            onClick={() => setQuery(stringifiedExamples.HogQLRaw)}
                        >
                            HogQL Debug
                        </LemonButton>
                        <LemonButton
                            active={query === stringifiedExamples.HogQLTable}
                            onClick={() => setQuery(stringifiedExamples.HogQLTable)}
                        >
                            HogQL Table
                        </LemonButton>
                        <LemonButton
                            active={query === stringifiedExamples.Events}
                            onClick={() => setQuery(stringifiedExamples.Events)}
                        >
                            Any Query
                        </LemonButton>
                        <LemonLabel>
                            <LemonSelect
                                placeholder={'More sample queries'}
                                options={Object.entries(stringifiedExamples)
                                    .filter(([k]) => k !== 'HogQLTable' && k !== 'HogQLRaw')
                                    .map(([k, v]) => {
                                        return { label: k, value: v }
                                    })}
                                onChange={(v) => {
                                    if (v) {
                                        setQuery(v)
                                    }
                                }}
                            />
                        </LemonLabel>
                    </>
                }
            />
            {parsed && parsed?.kind === 'HogQLQuery' ? (
                <HogQLDebug
                    query={parsed as HogQLQuery}
                    setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                />
            ) : (
                <Query
                    query={query}
                    setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                    context={{
                        showQueryEditor: showQueryEditor,
                    }}
                />
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: DebugScene,
    logic: debugSceneLogic,
}
