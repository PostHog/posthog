import { querySceneLogic } from './querySceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { stringifiedExamples } from '~/queries/examples'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

export function QueryScene(): JSX.Element {
    const { query } = useValues(querySceneLogic)
    const { setQuery } = useActions(querySceneLogic)

    let showEditor = true
    try {
        const parsed = JSON.parse(query)
        if (
            parsed &&
            parsed.kind == 'DataTableNode' &&
            parsed.source.kind == 'HogQLQuery' &&
            (parsed.full || parsed.showHogQLEditor)
        ) {
            showEditor = false
        }
    } catch (e) {
        // do nothing
    }

    return (
        <div className="QueryScene">
            <PageHeader
                title="Query Debugger"
                buttons={
                    <LemonLabel>
                        Example queries:{' '}
                        <LemonSelect
                            placeholder={'Select an example query'}
                            options={Object.entries(stringifiedExamples).map(([k, v]) => {
                                return { label: k, value: v }
                            })}
                            onChange={(v) => {
                                if (v) {
                                    setQuery(v)
                                }
                            }}
                        />
                    </LemonLabel>
                }
            />

            <Query
                query={query}
                setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                context={{
                    showQueryEditor: showEditor,
                }}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: QueryScene,
    logic: querySceneLogic,
}
