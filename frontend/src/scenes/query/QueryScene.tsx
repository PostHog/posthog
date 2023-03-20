import { querySceneLogic } from './querySceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/lemon-ui/Link'
import React from 'react'
import clsx from 'clsx'
import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { stringifiedExamples } from '~/queries/examples'

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
    } catch (e) {}

    return (
        <div className="QueryScene">
            <PageHeader title="Query Debugger" />
            <div className="space-y-2">
                <div>
                    For example:{' '}
                    {Object.entries(stringifiedExamples).map(([key, q], index) => (
                        <React.Fragment key={`query-${key}`}>
                            {index !== 0 ? ' • ' : ''}
                            <Link
                                onClick={(e) => {
                                    e.preventDefault()
                                    setQuery(q)
                                }}
                                className={clsx({ 'font-bold': q === query })}
                            >
                                {key}
                            </Link>
                        </React.Fragment>
                    ))}
                </div>
                <Query
                    query={query}
                    setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                    context={{
                        showQueryEditor: showEditor,
                    }}
                />
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: QueryScene,
    logic: querySceneLogic,
}
