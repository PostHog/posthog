import { querySceneLogic } from './querySceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { useActions, useValues } from 'kea'
import { PostHogQuery } from '~/queries/PostHogQuery'
import { PageHeader } from 'lib/components/PageHeader'
import { stringExamples } from 'scenes/query/examples'
import { Link } from 'lib/components/Link'
import React, { useEffect } from 'react'
import clsx from 'clsx'
import { LemonButton } from 'lib/components/LemonButton'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import schema from '~/queries/nodes.json'

export function QueryScene(): JSX.Element {
    const { queryInput, JSONQuery, error, inputChanged } = useValues(querySceneLogic)
    const { setQueryInput, setQuery } = useActions(querySceneLogic)
    const monaco = useMonaco()

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: [
                {
                    uri: 'https://internal.posthog.com/node-schema.json',
                    fileMatch: ['*'], // associate with our model
                    schema: schema,
                },
            ],
        })
    }, [monaco])

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
