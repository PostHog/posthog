import { querySceneLogic } from './querySceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { PostHogQuery } from '~/queries/PostHogQuery'
import { PageHeader } from 'lib/components/PageHeader'
import { stringExamples } from 'scenes/query/examples'
import { Link } from 'lib/components/Link'
import React from 'react'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import MonacoEditor from '@monaco-editor/react'

export function QueryScene(): JSX.Element {
    const { queryInput, JSONQuery, error, inputChanged } = useValues(querySceneLogic)
    const { setQueryInput, setQuery } = useActions(querySceneLogic)

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
                                onClick={(e) => {
                                    e.preventDefault()
                                    setQuery(query)
                                }}
                                className={clsx({ 'font-bold': queryInput === query })}
                            >
                                {key}
                            </Link>
                        </React.Fragment>
                    ))}
                </div>
                <MonacoEditor
                    theme="vs-light"
                    language={'json'}
                    value={queryInput}
                    onChange={(v) => setQueryInput(v ?? '')}
                    height={300}
                    options={{ minimap: { enabled: false } }}
                />
                {inputChanged ? (
                    <div>
                        <LemonButton onClick={() => setQuery(queryInput)} type="primary">
                            Run
                        </LemonButton>
                    </div>
                ) : null}
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
