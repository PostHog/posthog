import { querySceneLogic } from './querySceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/lemon-ui/Link'
import React from 'react'
import clsx from 'clsx'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { stringifiedExamples } from '~/queries/examples'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

export function QueryScene(): JSX.Element {
    const { query } = useValues(querySceneLogic)
    const { setQuery } = useActions(querySceneLogic)

    return (
        <div className="QueryScene">
            <PageHeader title="Query" />
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
                <QueryEditor query={query} setQuery={setQuery} />
                <div className="my-4">
                    <LemonDivider />
                </div>
                <Query query={query} setQuery={(query) => setQuery(JSON.stringify(query, null, 2))} />
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: QueryScene,
    logic: querySceneLogic,
}
