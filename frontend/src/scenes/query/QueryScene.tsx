import { querySceneLogic } from './querySceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { PostHogQuery } from '~/queries/PostHogQuery'
import { PageHeader } from 'lib/components/PageHeader'
import { stringExamples } from 'scenes/query/examples'
import { Link } from 'lib/components/Link'
import React from 'react'
import clsx from 'clsx'

export function QueryScene(): JSX.Element {
    const { queryInput, JSONQuery, error } = useValues(querySceneLogic)
    const { setQueryInput } = useActions(querySceneLogic)

    return (
        <div className="QueryScene">
            <PageHeader title="Query" />
            <div className="space-y-2 flex flex-col">
                <div>
                    For example:{' '}
                    {Object.entries(stringExamples).map(([key, query], index) => (
                        <React.Fragment key={`query-${key}`}>
                            {index !== 0 ? ' • ' : ''}
                            <Link
                                onClick={() => setQueryInput(query)}
                                className={clsx({ 'font-bold': queryInput === query })}
                            >
                                {key}
                            </Link>
                        </React.Fragment>
                    ))}
                </div>
                <LemonTextArea value={queryInput} onChange={(v) => setQueryInput(v)} />
                <strong>Response:</strong>
                {JSONQuery ? (
                    <PostHogQuery query={JSONQuery} />
                ) : (
                    <div className="text-danger border border-danger p-2">
                        <strong>Error parsing JSON:</strong> {error}
                    </div>
                )}
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: QueryScene,
    logic: querySceneLogic,
}
