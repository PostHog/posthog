import { Monaco } from '@monaco-editor/react'
import { IconDownload, IconPlayFilled } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { editor as importedEditor } from 'monaco-editor'
import { useState } from 'react'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AddVariableButton } from '~/queries/nodes/DataVisualization/Components/Variables/AddVariableButton'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { VariablesForInsight } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import {
    variablesLogic,
    VariablesLogicProps,
} from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import {
    dataVisualizationLogic,
    DataVisualizationLogicProps,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { displayLogic } from '~/queries/nodes/DataVisualization/displayLogic'
import { ItemMode } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { dataNodeKey, multitabEditorLogic } from './multitabEditorLogic'
import { OutputPane } from './OutputPane'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'

export function QueryWindow(): JSX.Element {
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []
    const codeEditorKey = `hogQLQueryEditor/${router.values.location.pathname}`

    const { featureFlags } = useValues(featureFlagLogic)

    const logic = multitabEditorLogic({
        key: codeEditorKey,
        monaco,
        editor,
    })

    const { allTabs, activeModelUri, queryInput, editingView, sourceQuery, isValidView } = useValues(logic)
    const {
        renameTab,
        selectTab,
        deleteTab,
        createTab,
        setQueryInput,
        runQuery,
        setError,
        setIsValidView,
        setMetadata,
        setMetadataLoading,
        saveAsView,
        setSourceQuery,
    } = useActions(logic)

    const logicKey = activeModelUri?.uri.path ?? dataNodeKey

    const { response } = useValues(
        dataNodeLogic({
            key: logicKey,
            query: sourceQuery.source,
            autoLoad: false,
        })
    )
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { updateDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    const dataVisualizationLogicProps: DataVisualizationLogicProps = {
        key: logicKey,
        query: sourceQuery,
        dashboardId: undefined,
        dataNodeCollectionId: logicKey,
        insightMode: ItemMode.Edit,
        loadPriority: undefined,
        cachedResults: undefined,
        variablesOverride: undefined,
        setQuery: setSourceQuery,
        localCache: false,
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: sourceQuery.source,
        key: logicKey,
        cachedResults: undefined,
        loadPriority: undefined,
        dataNodeCollectionId: logicKey,
        variablesOverride: undefined,
        autoLoad: false,
        localCache: false,
    }

    const variablesLogicProps: VariablesLogicProps = {
        key: dataVisualizationLogicProps.key,
        readOnly: false,
        queryInput,
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <BindLogic logic={dataVisualizationLogic} props={dataVisualizationLogicProps}>
                <BindLogic logic={displayLogic} props={{ key: dataVisualizationLogicProps.key }}>
                    <BindLogic logic={variablesLogic} props={variablesLogicProps}>
                        <BindLogic logic={variableModalLogic} props={{ key: dataVisualizationLogicProps.key }}>
                            <BindLogic logic={multitabEditorLogic} props={{ key: codeEditorKey, monaco, editor }}>
                                <div className="flex flex-1 flex-col h-full overflow-hidden">
                                    <div className="overflow-x-auto px-1">
                                        <QueryTabs
                                            models={allTabs}
                                            onClick={selectTab}
                                            onClear={deleteTab}
                                            onAdd={createTab}
                                            onRename={renameTab}
                                            activeModelUri={activeModelUri}
                                        />
                                    </div>
                                    {editingView && (
                                        <div className="h-5 bg-warning-highlight">
                                            <span className="text-xs">
                                                Editing {editingView.last_run_at ? 'materialized view' : 'view'} "
                                                {editingView.name}"
                                            </span>
                                        </div>
                                    )}
                                    <div className="flex flex-row justify-start align-center w-full ml-2 mr-2">
                                        <RunButton />
                                        <LemonDivider vertical />
                                        {editingView ? (
                                            <LemonButton
                                                onClick={() =>
                                                    updateDataWarehouseSavedQuery({
                                                        id: editingView.id,
                                                        query: sourceQuery.source,
                                                        types: response?.types ?? [],
                                                    })
                                                }
                                                disabledReason={updatingDataWarehouseSavedQuery ? 'Saving...' : ''}
                                                icon={<IconDownload />}
                                                type="tertiary"
                                                size="xsmall"
                                            >
                                                Update view
                                            </LemonButton>
                                        ) : (
                                            <LemonButton
                                                onClick={() => saveAsView()}
                                                disabledReason={isValidView ? '' : 'Some fields may need an alias'}
                                                icon={<IconDownload />}
                                                type="tertiary"
                                                size="xsmall"
                                            >
                                                Save as view
                                            </LemonButton>
                                        )}
                                        {featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES] && <LemonDivider vertical />}
                                        <AddVariableButton buttonProps={{ type: 'tertiary', size: 'xsmall' }} />
                                    </div>
                                    <QueryVariables />
                                    <QueryPane
                                        queryInput={queryInput}
                                        sourceQuery={sourceQuery.source}
                                        promptError={null}
                                        codeEditorProps={{
                                            queryKey: codeEditorKey,
                                            onChange: (v) => {
                                                setQueryInput(v ?? '')
                                            },
                                            onMount: (editor, monaco) => {
                                                setMonacoAndEditor([monaco, editor])
                                            },
                                            onPressCmdEnter: (value, selectionType) => {
                                                if (value && selectionType === 'selection') {
                                                    runQuery(value)
                                                } else {
                                                    runQuery()
                                                }
                                            },
                                            onError: (error, isValidView) => {
                                                setError(error)
                                                setIsValidView(isValidView)
                                            },
                                            onMetadata: (metadata) => {
                                                setMetadata(metadata)
                                            },
                                            onMetadataLoading: (loading) => {
                                                setMetadataLoading(loading)
                                            },
                                        }}
                                    />
                                    <InternalQueryWindow />
                                </div>
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

function RunButton(): JSX.Element {
    const { runQuery } = useActions(multitabEditorLogic)
    const { cancelQuery } = useActions(dataNodeLogic)
    const { responseLoading } = useValues(dataNodeLogic)

    return (
        <LemonButton
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    runQuery()
                }
            }}
            icon={responseLoading ? <IconCancel /> : <IconPlayFilled color="var(--success)" />}
            type="tertiary"
            size="xsmall"
        >
            {responseLoading ? 'Cancel' : 'Run'}
        </LemonButton>
    )
}

function QueryVariables(): JSX.Element {
    const { variablesForInsight } = useValues(variablesLogic)

    if (!variablesForInsight.length) {
        return <></>
    }

    return (
        <div className="py-2 px-4">
            <VariablesForInsight />
        </div>
    )
}

function InternalQueryWindow(): JSX.Element | null {
    const { cacheLoading } = useValues(multitabEditorLogic)

    // NOTE: hacky way to avoid flicker loading
    if (cacheLoading) {
        return null
    }

    return <OutputPane />
}
