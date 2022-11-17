import { querySceneLogic } from './querySceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/components/Link'
import React from 'react'
import clsx from 'clsx'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { PostHogQuery } from '~/queries/PostHogQuery/PostHogQuery'
import { useActions, useValues } from 'kea'
import { stringExamples } from '~/queries/examples'

export function QueryScene(): JSX.Element {
    const { query } = useValues(querySceneLogic)
    const { setQuery } = useActions(querySceneLogic)

    return (
        <div className="QueryScene">
            <PageHeader title="Query" />
            <div className="space-y-2 flex flex-col">
                <div>
                    For example:{' '}
                    {Object.entries(stringExamples).map(([key, q], index) => (
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
                <QueryEditor query={query} setQuery={setQuery} />

                <strong>Response:</strong>
                <PostHogQuery query={query} />
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: QueryScene,
    logic: querySceneLogic,
}
