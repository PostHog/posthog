import { Monaco } from '@monaco-editor/react'
import {
    IconBook,
    IconChevronRight,
    IconDatabase,
    IconDownload,
    IconGear,
    IconPencil,
    IconPlayFilled,
    IconSearch,
    IconSidebarClose,
} from '@posthog/icons'
import { LemonDivider, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import type { editor as importedEditor } from 'monaco-editor'
import { useMemo, useState } from 'react'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { FixErrorButton } from './components/FixErrorButton'
import { editorSizingLogic } from './editorSizingLogic'
import { EditorTabLevel, multitabEditorLogic } from './multitabEditorLogic'
import { OutputPane } from './OutputPane'
import { QueryHistoryModal } from './QueryHistoryModal'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { stringifiedExamples } from '~/queries/examples'

interface QueryWindowProps {
    onSetMonacoAndEditor: (monaco: Monaco, editor: importedEditor.IStandaloneCodeEditor) => void
}

const levelIcons: Record<EditorTabLevel, JSX.Element> = {
    new: <IconPencil />,
    editor: <IconPencil />,
    config: <IconGear />,
    source: <IconDatabase />,
    // Program: <IconPullRequest />,
}

const sampleQueries: Record<string, { input: string; level: EditorTabLevel }> = {
    SQL: {
        input: `SELECT toDate(toStartOfDay(timestamp)) AS date,
    concat(properties.$browser
                     , ' '
                     , properties.$browser_version) AS browser
                     , count () AS count
                FROM events`,
        level: 'source',
    },
    Trends: {
        input: stringifiedExamples['InsightTrendsQuery'],
        level: 'editor',
    },
    Funnel: {
        input: stringifiedExamples['InsightFunnelsQuery'],
        level: 'editor',
    },
    Retention: {
        input: stringifiedExamples['InsightRetentionQuery'],
        level: 'editor',
    },
    Stickiness: {
        input: stringifiedExamples['InsightStickinessQuery'],
        level: 'editor',
    },
    Lifecycle: {
        input: stringifiedExamples['InsightLifecycleQuery'],
        level: 'editor',
    },
    'User paths': {
        input: stringifiedExamples['InsightPathsQuery'],
        level: 'editor',
    },
    'Calendar heatmap': {
        input: stringifiedExamples['InsightLifecycleQuery'],
        level: 'editor',
    },
}

export function QueryWindow({ onSetMonacoAndEditor }: QueryWindowProps): JSX.Element {
    const codeEditorKey = `hogQLQueryEditor/${router.values.location.pathname}`

    const {
        allTabs,
        activeModelUri,
        queryInput,
        editingView,
        editingInsight,
        sourceQuery,
        inProgressViewEdits,
        changesToSave,
        originalQueryInput,
        suggestedQueryInput,
    } = useValues(multitabEditorLogic)
    const { activePanelIdentifier } = useValues(panelLayoutLogic)
    const { setActivePanelIdentifier } = useActions(panelLayoutLogic)

    const {
        renameTab,
        selectTab,
        deleteTab,
        createNewTab,
        setQueryInput,
        runQuery,
        setError,
        setMetadata,
        setMetadataLoading,
        saveAsView,
        updateView,
    } = useActions(multitabEditorLogic)
    const { openHistoryModal } = useActions(multitabEditorLogic)

    const { response } = useValues(dataNodeLogic)
    const { updatingDataWarehouseSavedQuery } = useValues(dataWarehouseViewsLogic)
    const { sidebarWidth } = useValues(editorSizingLogic)
    const { resetDefaultSidebarWidth } = useActions(editorSizingLogic)

    const isMaterializedView = !!editingView?.last_run_at || !!editingView?.sync_frequency

    const renderSidebarButton = (): JSX.Element => {
        if (activePanelIdentifier !== 'Database') {
            return (
                <LemonButton
                    onClick={() => setActivePanelIdentifier('Database')}
                    className="rounded-none"
                    icon={<IconSidebarClose />}
                    type="tertiary"
                    size="small"
                />
            )
        }

        if (sidebarWidth === 0) {
            return (
                <LemonButton
                    onClick={() => resetDefaultSidebarWidth()}
                    className="rounded-none"
                    icon={<IconSidebarClose />}
                    type="tertiary"
                    size="small"
                />
            )
        }

        return <></>
    }

    const [editingViewDisabledReason, EditingViewButtonIcon] = useMemo(() => {
        if (updatingDataWarehouseSavedQuery) {
            return ['Saving...', Spinner]
        }

        if (!response) {
            return ['Run query to update', IconDownload]
        }

        if (!changesToSave) {
            return ['No changes to save', IconDownload]
        }

        return [undefined, IconDownload]
    }, [updatingDataWarehouseSavedQuery, changesToSave, response])

    const activeLevel = activeModelUri?.level || 'new'

    return (
        <div className="flex flex-1 flex-col h-full overflow-hidden">
            <div className="flex flex-row overflow-x-auto">
                {renderSidebarButton()}
                <QueryTabs
                    models={allTabs}
                    onClick={selectTab}
                    onClear={deleteTab}
                    onAdd={createNewTab}
                    onRename={renameTab}
                    activeModelUri={activeModelUri}
                />
            </div>
            {(editingView || editingInsight) && (
                <div className="h-5 bg-warning-highlight">
                    <span className="pl-2 text-xs">
                        {editingView && (
                            <>
                                Editing {isMaterializedView ? 'materialized view' : 'view'} "{editingView.name}"
                            </>
                        )}
                        {editingInsight && (
                            <>
                                Editing insight "
                                <Link to={urls.insightView(editingInsight.short_id)}>{editingInsight.name}</Link>"
                            </>
                        )}
                    </span>
                </div>
            )}
            {activeLevel === 'new' || !activeLevel ? (
                <div className="flex flex-row justify-start align-center w-full pl-2 pr-2 bg-white dark:bg-black border-b">
                    <NewQuery />
                </div>
            ) : (
                <>
                    <div className="flex flex-row justify-start align-center w-full pl-2 pr-2 bg-white dark:bg-black border-b">
                        <QueryTypeSelector />
                        <QueryLevelSelector />
                        <LemonDivider vertical />
                        <RunButton />
                        <LemonDivider vertical />
                        {editingView && (
                            <>
                                <LemonButton
                                    onClick={() =>
                                        updateView({
                                            id: editingView.id,
                                            query: {
                                                ...sourceQuery.source,
                                                query: queryInput,
                                            },
                                            types: response && 'types' in response ? response?.types ?? [] : [],
                                            shouldRematerialize: isMaterializedView,
                                            edited_history_id: inProgressViewEdits[editingView.id],
                                        })
                                    }
                                    disabledReason={editingViewDisabledReason}
                                    icon={<EditingViewButtonIcon />}
                                    type="tertiary"
                                    size="xsmall"
                                    id={`sql-editor-query-window-update-${isMaterializedView ? 'materialize' : 'view'}`}
                                >
                                    {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
                                </LemonButton>
                                <LemonButton
                                    onClick={() => openHistoryModal()}
                                    icon={<IconBook />}
                                    type="tertiary"
                                    size="xsmall"
                                    id="sql-editor-query-window-history"
                                >
                                    History
                                </LemonButton>
                            </>
                        )}
                        {!editingInsight && !editingView && (
                            <>
                                <LemonButton
                                    onClick={() => saveAsView()}
                                    icon={<IconDownload />}
                                    type="tertiary"
                                    size="xsmall"
                                    data-attr="sql-editor-save-view-button"
                                    id="sql-editor-query-window-save-as-view"
                                >
                                    Save as view
                                </LemonButton>
                            </>
                        )}
                        <FixErrorButton type="tertiary" size="xsmall" source="action-bar" />
                    </div>
                </>
            )}
            <QueryPane
                className={activeLevel === 'new' || !activeLevel ? 'hidden' : ''}
                originalValue={originalQueryInput}
                queryInput={suggestedQueryInput}
                sourceQuery={sourceQuery.source}
                promptError={null}
                onRun={runQuery}
                codeEditorProps={{
                    queryKey: codeEditorKey,
                    onChange: (v) => {
                        setQueryInput(v ?? '')
                    },
                    onMount: (editor, monaco) => {
                        onSetMonacoAndEditor(monaco, editor)
                    },
                    onPressCmdEnter: (value, selectionType) => {
                        if (value && selectionType === 'selection') {
                            runQuery(value)
                        } else {
                            runQuery()
                        }
                    },
                    onError: (error) => {
                        setError(error)
                    },
                    onMetadata: (metadata) => {
                        setMetadata(metadata)
                    },
                    onMetadataLoading: (loading) => {
                        setMetadataLoading(loading)
                    },
                }}
            />
            {activeLevel === 'new' || !activeLevel ? null : <InternalQueryWindow />}
            <QueryHistoryModal />
        </div>
    )
}

function RunButton(): JSX.Element {
    const { runQuery } = useActions(multitabEditorLogic)
    const { cancelQuery } = useActions(dataNodeLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { metadata, queryInput, isSourceQueryLastRun } = useValues(multitabEditorLogic)

    const isUsingIndices = metadata?.isUsingIndices === 'yes'

    const [iconColor, tooltipContent] = useMemo(() => {
        if (isSourceQueryLastRun) {
            return ['var(--primary)', 'No changes to run']
        }

        if (!metadata || isUsingIndices || queryInput.trim().length === 0) {
            return ['var(--success)', 'New changes to run']
        }

        const tooltipContent = !isUsingIndices
            ? 'This query is not using indices optimally, which may result in slower performance.'
            : undefined

        return ['var(--warning)', tooltipContent]
    }, [metadata, isUsingIndices, queryInput, isSourceQueryLastRun])

    return (
        <LemonButton
            data-attr="sql-editor-run-button"
            onClick={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    runQuery()
                }
            }}
            icon={responseLoading ? <IconCancel /> : <IconPlayFilled color={iconColor} />}
            type="tertiary"
            size="xsmall"
            tooltip={tooltipContent}
        >
            {responseLoading ? 'Cancel' : 'Run'}
        </LemonButton>
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

function QueryTypeSelector(): JSX.Element | null {
    const { treeItemsNew } = useValues(projectTreeDataLogic)
    const { setQueryAndLevel } = useActions(multitabEditorLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive>
                    <IconSearch />
                    <strong className="whitespace-nowrap">SQL Query</strong>
                    <IconChevronRight className="rotate-90 group-data-[state=open]/button-root:rotate-270" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>

            <DropdownMenuContent loop align="start">
                <DropdownMenuLabel>Select query</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                    <Link
                        onClick={() => {
                            const q = sampleQueries.SQL
                            if (q) {
                                setQueryAndLevel(q.input, q.level)
                            }
                        }}
                        buttonProps={{
                            menuItem: true,
                            // active: selectedLabel === 'SQL query',
                        }}
                    >
                        <IconDatabase /> SQL query
                    </Link>
                </DropdownMenuItem>
                <DropdownMenuLabel>Insights</DropdownMenuLabel>
                <DropdownMenuSeparator />

                {treeItemsNew
                    .find(({ name }) => name === 'Insight')
                    ?.children?.sort((a, b) => (a.visualOrder ?? 0) - (b.visualOrder ?? 0))
                    ?.map((child) => (
                        <DropdownMenuItem asChild>
                            <Link
                                onClick={() => {
                                    const q = sampleQueries[child.name]
                                    if (q) {
                                        setQueryAndLevel(q.input, q.level)
                                    }
                                }}
                                buttonProps={{
                                    menuItem: true,
                                    // active: selectedLabel === child.name,
                                }}
                            >
                                {child.icon}
                                {child.name}
                            </Link>
                        </DropdownMenuItem>
                    ))}

                <DropdownMenuSeparator />
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger asChild>
                        <Link
                            onClick={() => {}}
                            buttonProps={{
                                menuItem: true,
                            }}
                        >
                            My programs
                            <IconChevronRight className="group-data-[state=open]/button-root:rotate-180" />
                        </Link>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                        <DropdownMenuItem asChild>
                            <Link
                                to={`/debug/hog#repl=%5B%7B"code"%3A"%2F%2F%20<Pivot%20query%3D%7Bselect%20col1%2C%20col2%2C%20sum()%20from%20...%7D%20label%3D'TopRight'%20default%3D%7B0%7D%20%2F>%5Cnfun%20Pivot(props)%20%7B%5Cn%20%20%20%20let%20result%20%3A%3D%20run(props.query)%5Cn%20%20%20%20let%20dates%20%3A%3D%20arrayMap(row%20->%20row.1%2C%20result.results)%5Cn%20%20%20%20let%20columns%20%3A%3D%20%5Bprops.label%5D%5Cn%20%20%20%20for%20(let%20date%20in%20dates)%20%7B%20columns%20%3A%3D%20arrayPushBack(columns%2C%20date)%20%7D%5Cn%20%20%20%20let%20cache%20%3A%3D%20%7B%7D%5Cn%20%20%20%20let%20sessions%20%3A%3D%20%7B%7D%5Cn%20%20%20%20for%20(let%20row%20in%20result.results)%20%7B%5Cn%20%20%20%20%20%20%20%20cache%5Bf'%7Brow.1%7D-%7Brow.2%7D'%5D%20%3A%3D%20row.3%5Cn%20%20%20%20%20%20%20%20sessions%5Brow.2%5D%20%3A%3D%20true%5Cn%20%20%20%20%7D%5Cn%20%20%20%20let%20rows%20%3A%3D%20arrayMap(session%20->%20%7B%5Cn%20%20%20%20%20%20%20%20let%20row%20%3A%3D%20%5Bsession%5D%5Cn%20%20%20%20%20%20%20%20for%20(let%20date%20in%20dates)%20%7B%20row%20%3A%3D%20arrayPushBack(row%2C%20ifNull(cache%5Bf'%7Bdate%7D-%7Bsession%7D'%5D%2C%20props.default))%20%7D%5Cn%20%20%20%20%20%20%20%20return%20row%5Cn%20%20%20%20%7D%2C%20keys(sessions))%5Cn%20%20%20%20let%20table%20%3A%3D%20%7B%20'columns'%3A%20columns%2C%20'results'%3A%20rows%20%7D%5Cn%20%20%20%20return%20table%5Cn%7D%5Cn%5Cnfun%20Layout(props%2C%20results)%20%7B%5Cn%20%20%20%20let%20reactComponent%20%3A%3D%20()%20->%20''%5Cn%20%20%20%20return%20(%5Cn%20%20%20%20%20%20%20%20<Split>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20<Tabs>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20<Tab%20title%3D'Editor'>...<%2FTab>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20<Tab%20title%3D'Input'>...<%2FTab>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20<%2FTabs>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20<Tabs>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20<Tab%20title%3D'Table'><Pivot%20query%3D%7Bprops.query%7D%20label%3D%7Bprops.label%7D%20default%3D%7Bprops.default%7D%20%2F><%2FTab>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20<Tab%20title%3D'Graph'>%7BreactComponent('InsightVizNode'%2C%20props.query)%7D<%2FTab>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20<%2FTabs>%5Cn%20%20%20%20%20%20%20%20<%2FSplit>%5Cn%20%20%20%20)%5Cn%7D%5Cn%5Cnprint(%5Cn%20%20%20%20<Pivot%5Cn%20%20%20%20%20%20%20%20query%3D%7B(%5Cn%20%20%20%20%20%20%20%20%20%20%20%20select%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20toDate(toStartOfDay(timestamp))%2C%20%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20f'%7Bproperties.%24browser%7D%20%7Bproperties.%24browser_version%7D'%20as%20browser%2C%20%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20count()%20%5Cn%20%20%20%20%20%20%20%20%20%20%20%20from%20events%20%5Cn%20%20%20%20%20%20%20%20%20%20%20%20where%20%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20event%20%3D%20'%24pageview'%20and%20%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20timestamp%20>%20now()%20-%20interval%201%20week%20%5Cn%20%20%20%20%20%20%20%20%20%20%20%20group%20by%20toStartOfDay(timestamp)%2C%20browser%5Cn%20%20%20%20%20%20%20%20)%7D%5Cn%20%20%20%20%20%20%20%20default%3D%7B0%7D%5Cn%20%20%20%20%20%20%20%20label%3D%7B'Browser'%7D%5Cn%20%20%20%20%2F>%5Cn)"%2C"status"%3A"success"%2C"bytecode"%3A%5B52%2C"Pivot"%2C1%2C0%2C289%2C36%2C0%2C32%2C"query"%2C45%2C2%2C"run"%2C1%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C1%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C36%2C0%2C32%2C"label"%2C45%2C43%2C1%2C36%2C2%2C36%2C4%2C2%2C"values"%2C1%2C33%2C1%2C36%2C5%2C2%2C"length"%2C1%2C31%2C36%2C7%2C36%2C6%2C16%2C40%2C25%2C36%2C5%2C36%2C6%2C45%2C37%2C8%2C36%2C3%2C36%2C8%2C2%2C"arrayPushBack"%2C2%2C37%2C3%2C36%2C6%2C33%2C1%2C6%2C37%2C6%2C39%2C-32%2C35%2C35%2C35%2C35%2C35%2C42%2C0%2C42%2C0%2C36%2C1%2C32%2C"results"%2C45%2C36%2C6%2C2%2C"values"%2C1%2C33%2C1%2C36%2C7%2C2%2C"length"%2C1%2C31%2C36%2C9%2C36%2C8%2C16%2C40%2C48%2C36%2C7%2C36%2C8%2C45%2C37%2C10%2C36%2C4%2C36%2C10%2C33%2C1%2C45%2C32%2C"-"%2C36%2C10%2C33%2C2%2C45%2C2%2C"concat"%2C3%2C36%2C10%2C33%2C3%2C45%2C46%2C36%2C5%2C36%2C10%2C33%2C2%2C45%2C29%2C46%2C36%2C8%2C33%2C1%2C6%2C37%2C8%2C39%2C-55%2C35%2C35%2C35%2C35%2C35%2C52%2C"lambda"%2C1%2C3%2C78%2C36%2C0%2C43%2C1%2C55%2C0%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C43%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C36%2C1%2C55%2C1%2C36%2C6%2C32%2C"-"%2C36%2C0%2C2%2C"concat"%2C3%2C45%2C47%2C6%2C35%2C55%2C2%2C32%2C"default"%2C45%2C2%2C"arrayPushBack"%2C2%2C37%2C1%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-50%2C35%2C35%2C35%2C35%2C35%2C36%2C1%2C38%2C35%2C53%2C3%2Ctrue%2C2%2Ctrue%2C4%2Ctrue%2C0%2C36%2C5%2C2%2C"keys"%2C1%2C2%2C"arrayMap"%2C2%2C32%2C"columns"%2C36%2C3%2C32%2C"results"%2C36%2C6%2C42%2C2%2C36%2C7%2C38%2C35%2C35%2C35%2C57%2C35%2C57%2C35%2C53%2C0%2C52%2C"Layout"%2C2%2C1%2C140%2C52%2C"lambda"%2C0%2C0%2C3%2C32%2C""%2C38%2C53%2C0%2C32%2C"__hx_tag"%2C32%2C"Split"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Tabs"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Editor"%2C32%2C"children"%2C32%2C"..."%2C43%2C1%2C42%2C3%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Input"%2C32%2C"children"%2C32%2C"..."%2C43%2C1%2C42%2C3%2C43%2C2%2C42%2C2%2C32%2C"__hx_tag"%2C32%2C"Tabs"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Table"%2C32%2C"children"%2C32%2C"query"%2C36%2C0%2C32%2C"query"%2C45%2C32%2C"label"%2C36%2C0%2C32%2C"label"%2C45%2C32%2C"default"%2C36%2C0%2C32%2C"default"%2C45%2C42%2C3%2C55%2C0%2C54%2C1%2C43%2C1%2C42%2C3%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Graph"%2C32%2C"children"%2C32%2C"InsightVizNode"%2C36%2C0%2C32%2C"query"%2C45%2C36%2C2%2C54%2C2%2C43%2C1%2C42%2C3%2C43%2C2%2C42%2C2%2C43%2C2%2C42%2C2%2C38%2C35%2C53%2C1%2Ctrue%2C0%2C32%2C"query"%2C32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toDate"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toStartOfDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Alias"%2C32%2C"alias"%2C32%2C"browser"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"concat"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"properties"%2C32%2C"%24browser"%2C43%2C2%2C42%2C2%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"%20"%2C42%2C2%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"properties"%2C32%2C"%24browser_version"%2C43%2C2%2C42%2C2%2C43%2C3%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"hidden"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C43%2C3%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"events"%2C43%2C1%2C42%2C2%2C42%2C2%2C32%2C"where"%2C32%2C"__hx_ast"%2C32%2C"And"%2C32%2C"exprs"%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"%24pageview"%2C42%2C2%2C32%2C"op"%2C32%2C"%3D%3D"%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"ArithmeticOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"now"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toIntervalWeek"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"op"%2C32%2C"-"%2C42%2C4%2C32%2C"op"%2C32%2C">"%2C42%2C4%2C43%2C2%2C42%2C2%2C32%2C"group_by"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toStartOfDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"browser"%2C43%2C1%2C42%2C2%2C43%2C2%2C42%2C5%2C32%2C"default"%2C33%2C0%2C32%2C"label"%2C32%2C"Browser"%2C42%2C3%2C36%2C0%2C54%2C1%2C2%2C"print"%2C1%2C35%5D%2C"locals"%3A%5B%5B"Pivot"%2C1%2Ctrue%5D%2C%5B"Layout"%2C1%2Cfalse%5D%5D%2C"print"%3A%5B%5B%7B"columns"%3A%5B"Browser"%2C"2025-07-16"%2C"2025-07-17"%2C"2025-07-18"%2C"2025-07-15"%2C"2025-07-22"%2C"2025-07-16"%5D%2C"results"%3A%5B%5B"Chrome%20137"%2C85%2C0%2C0%2C7%2C0%2C85%5D%2C%5B"Chrome%20138"%2C7%2C1080%2C686%2C0%2C252%2C7%5D%5D%7D%5D%5D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C52%2C"Pivot"%2C1%2C0%2C289%2C36%2C0%2C32%2C"query"%2C45%2C2%2C"run"%2C1%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C1%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C36%2C0%2C32%2C"label"%2C45%2C43%2C1%2C36%2C2%2C36%2C4%2C2%2C"values"%2C1%2C33%2C1%2C36%2C5%2C2%2C"length"%2C1%2C31%2C36%2C7%2C36%2C6%2C16%2C40%2C25%2C36%2C5%2C36%2C6%2C45%2C37%2C8%2C36%2C3%2C36%2C8%2C2%2C"arrayPushBack"%2C2%2C37%2C3%2C36%2C6%2C33%2C1%2C6%2C37%2C6%2C39%2C-32%2C35%2C35%2C35%2C35%2C35%2C42%2C0%2C42%2C0%2C36%2C1%2C32%2C"results"%2C45%2C36%2C6%2C2%2C"values"%2C1%2C33%2C1%2C36%2C7%2C2%2C"length"%2C1%2C31%2C36%2C9%2C36%2C8%2C16%2C40%2C48%2C36%2C7%2C36%2C8%2C45%2C37%2C10%2C36%2C4%2C36%2C10%2C33%2C1%2C45%2C32%2C"-"%2C36%2C10%2C33%2C2%2C45%2C2%2C"concat"%2C3%2C36%2C10%2C33%2C3%2C45%2C46%2C36%2C5%2C36%2C10%2C33%2C2%2C45%2C29%2C46%2C36%2C8%2C33%2C1%2C6%2C37%2C8%2C39%2C-55%2C35%2C35%2C35%2C35%2C35%2C52%2C"lambda"%2C1%2C3%2C78%2C36%2C0%2C43%2C1%2C55%2C0%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C43%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C36%2C1%2C55%2C1%2C36%2C6%2C32%2C"-"%2C36%2C0%2C2%2C"concat"%2C3%2C45%2C47%2C6%2C35%2C55%2C2%2C32%2C"default"%2C45%2C2%2C"arrayPushBack"%2C2%2C37%2C1%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-50%2C35%2C35%2C35%2C35%2C35%2C36%2C1%2C38%2C35%2C53%2C3%2Ctrue%2C2%2Ctrue%2C4%2Ctrue%2C0%2C36%2C5%2C2%2C"keys"%2C1%2C2%2C"arrayMap"%2C2%2C32%2C"columns"%2C36%2C3%2C32%2C"results"%2C36%2C6%2C42%2C2%2C36%2C7%2C38%2C35%2C35%2C35%2C57%2C35%2C57%2C35%2C53%2C0%2C52%2C"Layout"%2C2%2C1%2C140%2C52%2C"lambda"%2C0%2C0%2C3%2C32%2C""%2C38%2C53%2C0%2C32%2C"__hx_tag"%2C32%2C"Split"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Tabs"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Editor"%2C32%2C"children"%2C32%2C"..."%2C43%2C1%2C42%2C3%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Input"%2C32%2C"children"%2C32%2C"..."%2C43%2C1%2C42%2C3%2C43%2C2%2C42%2C2%2C32%2C"__hx_tag"%2C32%2C"Tabs"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Table"%2C32%2C"children"%2C32%2C"query"%2C36%2C0%2C32%2C"query"%2C45%2C32%2C"label"%2C36%2C0%2C32%2C"label"%2C45%2C32%2C"default"%2C36%2C0%2C32%2C"default"%2C45%2C42%2C3%2C55%2C0%2C54%2C1%2C43%2C1%2C42%2C3%2C32%2C"__hx_tag"%2C32%2C"Tab"%2C32%2C"title"%2C32%2C"Graph"%2C32%2C"children"%2C32%2C"InsightVizNode"%2C36%2C0%2C32%2C"query"%2C45%2C36%2C2%2C54%2C2%2C43%2C1%2C42%2C3%2C43%2C2%2C42%2C2%2C43%2C2%2C42%2C2%2C38%2C35%2C53%2C1%2Ctrue%2C0%2C32%2C"query"%2C32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toDate"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toStartOfDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Alias"%2C32%2C"alias"%2C32%2C"browser"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"concat"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"properties"%2C32%2C"%24browser"%2C43%2C2%2C42%2C2%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"%20"%2C42%2C2%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"properties"%2C32%2C"%24browser_version"%2C43%2C2%2C42%2C2%2C43%2C3%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"hidden"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C43%2C3%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"events"%2C43%2C1%2C42%2C2%2C42%2C2%2C32%2C"where"%2C32%2C"__hx_ast"%2C32%2C"And"%2C32%2C"exprs"%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"%24pageview"%2C42%2C2%2C32%2C"op"%2C32%2C"%3D%3D"%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"ArithmeticOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"now"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toIntervalWeek"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"op"%2C32%2C"-"%2C42%2C4%2C32%2C"op"%2C32%2C">"%2C42%2C4%2C43%2C2%2C42%2C2%2C32%2C"group_by"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toStartOfDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"browser"%2C43%2C1%2C42%2C2%2C43%2C2%2C42%2C5%2C32%2C"default"%2C33%2C0%2C32%2C"label"%2C32%2C"Browser"%2C42%2C3%2C36%2C0%2C54%2C1%2C2%2C"print"%2C1%5D%7D%7D%2C"stack"%3A%5B%7B"__hogClosure__"%3Atrue%2C"callable"%3A%7B"__hogCallable__"%3A"local"%2C"name"%3A"Pivot"%2C"chunk"%3A"root"%2C"argCount"%3A1%2C"upvalueCount"%3A0%2C"ip"%3A7%7D%2C"upvalues"%3A%5B%5D%7D%2C%7B"__hogClosure__"%3Atrue%2C"callable"%3A%7B"__hogCallable__"%3A"local"%2C"name"%3A"Layout"%2C"chunk"%3A"root"%2C"argCount"%3A2%2C"upvalueCount"%3A1%2C"ip"%3A303%7D%2C"upvalues"%3A%5B1%5D%7D%2Cnull%5D%2C"upvalues"%3A%5B%7B"__hogUpValue__"%3Atrue%2C"id"%3A1%2C"location"%3A0%2C"closed"%3Afalse%2C"value"%3Anull%7D%2C%7B"__hogUpValue__"%3Atrue%2C"id"%3A4%2C"location"%3A2%2C"closed"%3Atrue%2C"value"%3A%7B"query"%3A%7B"__hx_ast"%3A"SelectQuery"%2C"select"%3A%5B%7B"__hx_ast"%3A"Call"%2C"name"%3A"toDate"%2C"args"%3A%5B%7B"__hx_ast"%3A"Call"%2C"name"%3A"toStartOfDay"%2C"args"%3A%5B%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"timestamp"%5D%7D%5D%2C"distinct"%3Afalse%7D%5D%2C"distinct"%3Afalse%7D%2C%7B"__hx_ast"%3A"Alias"%2C"alias"%3A"browser"%2C"expr"%3A%7B"__hx_ast"%3A"Call"%2C"name"%3A"concat"%2C"args"%3A%5B%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"properties"%2C"%24browser"%5D%7D%2C%7B"__hx_ast"%3A"Constant"%2C"value"%3A"%20"%7D%2C%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"properties"%2C"%24browser_version"%5D%7D%5D%2C"distinct"%3Afalse%7D%2C"hidden"%3Afalse%7D%2C%7B"__hx_ast"%3A"Call"%2C"name"%3A"count"%2C"args"%3A%5B%5D%2C"distinct"%3Afalse%7D%5D%2C"select_from"%3A%7B"__hx_ast"%3A"JoinExpr"%2C"table"%3A%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"events"%5D%7D%7D%2C"where"%3A%7B"__hx_ast"%3A"And"%2C"exprs"%3A%5B%7B"__hx_ast"%3A"CompareOperation"%2C"left"%3A%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"event"%5D%7D%2C"right"%3A%7B"__hx_ast"%3A"Constant"%2C"value"%3A"%24pageview"%7D%2C"op"%3A"%3D%3D"%7D%2C%7B"__hx_ast"%3A"CompareOperation"%2C"left"%3A%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"timestamp"%5D%7D%2C"right"%3A%7B"__hx_ast"%3A"ArithmeticOperation"%2C"left"%3A%7B"__hx_ast"%3A"Call"%2C"name"%3A"now"%2C"args"%3A%5B%5D%2C"distinct"%3Afalse%7D%2C"right"%3A%7B"__hx_ast"%3A"Call"%2C"name"%3A"toIntervalWeek"%2C"args"%3A%5B%7B"__hx_ast"%3A"Constant"%2C"value"%3A1%7D%5D%2C"distinct"%3Afalse%7D%2C"op"%3A"-"%7D%2C"op"%3A">"%7D%5D%7D%2C"group_by"%3A%5B%7B"__hx_ast"%3A"Call"%2C"name"%3A"toStartOfDay"%2C"args"%3A%5B%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"timestamp"%5D%7D%5D%2C"distinct"%3Afalse%7D%2C%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"browser"%5D%7D%5D%7D%2C"default"%3A0%2C"label"%3A"Browser"%7D%7D%2C%7B"__hogUpValue__"%3Atrue%2C"id"%3A2%2C"location"%3A4%2C"closed"%3Atrue%2C"value"%3A%5B"2025-07-16"%2C"2025-07-17"%2C"2025-07-18"%2C"2025-07-15"%2C"2025-07-22"%2C"2025-07-16"%5D%7D%2C%7B"__hogUpValue__"%3Atrue%2C"id"%3A3%2C"location"%3A6%2C"closed"%3Atrue%2C"value"%3A%7B"2025-07-16-Chrome%20137"%3A85%2C"2025-07-17-Chrome%20138"%3A1080%2C"2025-07-18-Chrome%20138"%3A686%2C"2025-07-15-Chrome%20137"%3A7%2C"2025-07-22-Chrome%20138"%3A252%2C"2025-07-16-Chrome%20138"%3A7%7D%7D%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A1090%2C"asyncSteps"%3A1%2C"syncDuration"%3A6%2C"maxMemUsed"%3A6717%7D%7D%5D&code=`}
                                buttonProps={{
                                    menuItem: true,
                                }}
                            >
                                Pivot tables
                            </Link>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <Link
                                to={`/debug/hog#repl=%5B%7B"code"%3A"let%20results%20%3A%3D%20run(select%20count()%2C%20event%20from%20events%20where%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20event%20order%20by%20count()%20desc%20limit%2010)%5Cn%5Cnlet%20events%20%3A%3D%20arrayMap(a%20->%20a.2%2C%20results.results)%5Cnprint('running')%5Cn%5Cnfor%20(let%20event%20in%20events)%20%7B%5Cn%20%20let%20query%20%3A%3D%20(select%20count()%2C%20toStartOfDay(timestamp)%20as%20day%20from%20events%20where%20event%20%3D%20%7Bevent%7D%20and%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20day%20order%20by%20day)%5Cn%20%20let%20data%20%3A%3D%20run(query)%5Cn%20%20print(%5Cn%20%20%20%20<div>%5Cn%20%20%20%20%20%20<td>%7Bevent%7D<%2Ftd>%5Cn%20%20%20%20%20%20<td><Sparkline%20%5Cn%20%20%20%20%20%20%20%20type%3D'line'%5Cn%20%20%20%20%20%20%20%20color%3D'blue'%5Cn%20%20%20%20%20%20%20%20data%3D%7BarrayMap(a%20->%20a.1%2C%20data.results)%7D%20%5Cn%20%20%20%20%20%20%20%20labels%3D%7BarrayMap(a%20->%20a.2%2C%20data.results)%7D%20%5Cn%20%20%20%20%20%20%2F><%2Ftd>%5Cn%20%20%20%20<%2Fdiv>%5Cn%20%20)%5Cn%7D%5Cnprint('We%20are%20done!')"%2C"status"%3A"success"%2C"bytecode"%3A%5B32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C43%2C2%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"events"%2C43%2C1%2C42%2C2%2C42%2C2%2C32%2C"where"%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"ArithmeticOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"now"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toIntervalDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C7%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"op"%2C32%2C"-"%2C42%2C4%2C32%2C"op"%2C32%2C">"%2C42%2C4%2C32%2C"group_by"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"order_by"%2C32%2C"__hx_ast"%2C32%2C"OrderExpr"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"order"%2C32%2C"DESC"%2C42%2C3%2C43%2C1%2C32%2C"limit"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C10%2C42%2C2%2C42%2C7%2C2%2C"run"%2C1%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C0%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"running"%2C2%2C"print"%2C1%2C35%2C36%2C1%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C385%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Alias"%2C32%2C"alias"%2C32%2C"day"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toStartOfDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"hidden"%2C33%2Cfalse%2C42%2C4%2C43%2C2%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"events"%2C43%2C1%2C42%2C2%2C42%2C2%2C32%2C"where"%2C32%2C"__hx_ast"%2C32%2C"And"%2C32%2C"exprs"%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C36%2C6%2C32%2C"op"%2C32%2C"%3D%3D"%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"ArithmeticOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"now"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toIntervalDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C7%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"op"%2C32%2C"-"%2C42%2C4%2C32%2C"op"%2C32%2C">"%2C42%2C4%2C43%2C2%2C42%2C2%2C32%2C"group_by"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"day"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"order_by"%2C32%2C"__hx_ast"%2C32%2C"OrderExpr"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"day"%2C43%2C1%2C42%2C2%2C32%2C"order"%2C32%2C"ASC"%2C42%2C3%2C43%2C1%2C42%2C6%2C36%2C7%2C2%2C"run"%2C1%2C32%2C"__hx_tag"%2C32%2C"div"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"td"%2C32%2C"children"%2C36%2C6%2C43%2C1%2C42%2C2%2C32%2C"__hx_tag"%2C32%2C"td"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Sparkline"%2C32%2C"type"%2C32%2C"line"%2C32%2C"color"%2C32%2C"blue"%2C32%2C"data"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C8%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"labels"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C8%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C42%2C5%2C43%2C1%2C42%2C2%2C43%2C2%2C42%2C2%2C2%2C"print"%2C1%2C35%2C35%2C35%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-392%2C35%2C35%2C35%2C35%2C35%2C32%2C"We%20are%20done!"%2C2%2C"print"%2C1%2C35%5D%2C"locals"%3A%5B%5B"results"%2C1%2Cfalse%5D%2C%5B"events"%2C1%2Cfalse%5D%5D%2C"print"%3A%5B%5B"running"%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"spinner_unloaded"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B16%2C351%2C4632%2C4904%2C2%2C9%2C1094%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-20T00%3A00%3A00Z"%2C"2025-07-21T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"%24feature_flag_called"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B23%2C1091%2C3307%2C2717%2C1976%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"query%20completed"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B141%2C1350%2C1641%2C1514%2C627%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"memory_usage"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B473%2C976%2C1194%2C1286%2C1%2C28%2C391%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-20T00%3A00%3A00Z"%2C"2025-07-21T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"%24%24heatmap"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B158%2C627%2C623%2C1114%2C713%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"%24pageview"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B7%2C92%2C1080%2C686%2C252%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"%24exception"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B105%2C134%2C133%2C103%2C941%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"%24groupidentify"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B3%2C153%2C434%2C364%2C239%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"client_request_failure"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B96%2C95%2C107%2C48%2C726%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B%7B"__hx_tag"%3A"div"%2C"children"%3A%5B%7B"__hx_tag"%3A"td"%2C"children"%3A%5B"query%20failed"%5D%7D%2C%7B"__hx_tag"%3A"td"%2C"children"%3A%5B%7B"__hx_tag"%3A"Sparkline"%2C"type"%3A"line"%2C"color"%3A"blue"%2C"data"%3A%5B91%2C86%2C79%2C45%2C738%5D%2C"labels"%3A%5B"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%7D%5D%7D%5D%7D%5D%2C%5B"We%20are%20done!"%5D%5D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C43%2C2%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"events"%2C43%2C1%2C42%2C2%2C42%2C2%2C32%2C"where"%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"ArithmeticOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"now"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toIntervalDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C7%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"op"%2C32%2C"-"%2C42%2C4%2C32%2C"op"%2C32%2C">"%2C42%2C4%2C32%2C"group_by"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"order_by"%2C32%2C"__hx_ast"%2C32%2C"OrderExpr"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"order"%2C32%2C"DESC"%2C42%2C3%2C43%2C1%2C32%2C"limit"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C10%2C42%2C2%2C42%2C7%2C2%2C"run"%2C1%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C0%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"running"%2C2%2C"print"%2C1%2C35%2C36%2C1%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C385%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"count"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"Alias"%2C32%2C"alias"%2C32%2C"day"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toStartOfDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"hidden"%2C33%2Cfalse%2C42%2C4%2C43%2C2%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"events"%2C43%2C1%2C42%2C2%2C42%2C2%2C32%2C"where"%2C32%2C"__hx_ast"%2C32%2C"And"%2C32%2C"exprs"%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"event"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C36%2C6%2C32%2C"op"%2C32%2C"%3D%3D"%2C42%2C4%2C32%2C"__hx_ast"%2C32%2C"CompareOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"timestamp"%2C43%2C1%2C42%2C2%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"ArithmeticOperation"%2C32%2C"left"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"now"%2C32%2C"args"%2C43%2C0%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"right"%2C32%2C"__hx_ast"%2C32%2C"Call"%2C32%2C"name"%2C32%2C"toIntervalDay"%2C32%2C"args"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C7%2C42%2C2%2C43%2C1%2C32%2C"distinct"%2C33%2Cfalse%2C42%2C4%2C32%2C"op"%2C32%2C"-"%2C42%2C4%2C32%2C"op"%2C32%2C">"%2C42%2C4%2C43%2C2%2C42%2C2%2C32%2C"group_by"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"day"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"order_by"%2C32%2C"__hx_ast"%2C32%2C"OrderExpr"%2C32%2C"expr"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"day"%2C43%2C1%2C42%2C2%2C32%2C"order"%2C32%2C"ASC"%2C42%2C3%2C43%2C1%2C42%2C6%2C36%2C7%2C2%2C"run"%2C1%2C32%2C"__hx_tag"%2C32%2C"div"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"td"%2C32%2C"children"%2C36%2C6%2C43%2C1%2C42%2C2%2C32%2C"__hx_tag"%2C32%2C"td"%2C32%2C"children"%2C32%2C"__hx_tag"%2C32%2C"Sparkline"%2C32%2C"type"%2C32%2C"line"%2C32%2C"color"%2C32%2C"blue"%2C32%2C"data"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C8%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"labels"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C8%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C42%2C5%2C43%2C1%2C42%2C2%2C43%2C2%2C42%2C2%2C2%2C"print"%2C1%2C35%2C35%2C35%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-392%2C35%2C35%2C35%2C35%2C35%2C32%2C"We%20are%20done!"%2C2%2C"print"%2C1%5D%7D%7D%2C"stack"%3A%5B%7B"results"%3A%5B%5B11008%2C"spinner_unloaded"%5D%2C%5B9114%2C"%24feature_flag_called"%5D%2C%5B5273%2C"query%20completed"%5D%2C%5B4349%2C"memory_usage"%5D%2C%5B3235%2C"%24%24heatmap"%5D%2C%5B2117%2C"%24pageview"%5D%2C%5B1416%2C"%24exception"%5D%2C%5B1193%2C"%24groupidentify"%5D%2C%5B1072%2C"client_request_failure"%5D%2C%5B1039%2C"query%20failed"%5D%5D%2C"columns"%3A%5B"count()"%2C"event"%5D%7D%2C%5B"spinner_unloaded"%2C"%24feature_flag_called"%2C"query%20completed"%2C"memory_usage"%2C"%24%24heatmap"%2C"%24pageview"%2C"%24exception"%2C"%24groupidentify"%2C"client_request_failure"%2C"query%20failed"%5D%2Cnull%5D%2C"upvalues"%3A%5B%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A5137%2C"asyncSteps"%3A11%2C"syncDuration"%3A70%2C"maxMemUsed"%3A5454%7D%7D%5D&code=`}
                                buttonProps={{
                                    menuItem: true,
                                }}
                            >
                                Database crawler
                            </Link>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <Link
                                to={`/debug/hog#repl=%5B%7B"code"%3A"%2F%2F%20let%20query%20%3A%3D%20(select%20*%20from%20events%20order%20by%20timestamp%20desc%20limit%2010)%5Cnlet%20query%20%3A%3D%20(%5Cn%20%20%20%20select%20*%20from%20%5Cn%20%20%20%20%20%20%20%20<TrendsQuery%5Cn%20%20%20%20%20%20%20%20%20%20%20%20series%3D%7B%5B%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20<EventsNode%20event%3D'%24pageview'%20math%3D'total'%20%2F>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%5D%7D%5Cn%20%20%20%20%20%20%20%20%20%20%20%20dateRange%3D%7B<DateRange%20date_from%3D'-90d'%20%2F>%7D%5Cn%20%20%20%20%20%20%20%20%20%20%20%20interval%3D'day'%5Cn%20%20%20%20%20%20%20%20%20%20%20%20trendsFilter%3D%7B%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20<TrendsFilter%20smoothingIntervals%3D%7B7%7D%20%2F>%5Cn%20%20%20%20%20%20%20%20%20%20%20%20%7D%5Cn%20%20%20%20%20%20%20%20%2F>%5Cn)%5Cn%5Cnprint(run(query))"%2C"status"%3A"success"%2C"bytecode"%3A%5B32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"*"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"TrendsQuery"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"series"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Array"%2C32%2C"exprs"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"EventsNode"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"event"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"%24pageview"%2C42%2C2%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"math"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"total"%2C42%2C2%2C42%2C3%2C43%2C2%2C42%2C3%2C43%2C1%2C42%2C2%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"dateRange"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"DateRange"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"date_from"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"-90d"%2C42%2C2%2C42%2C3%2C43%2C1%2C42%2C3%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"interval"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"day"%2C42%2C2%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"trendsFilter"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"TrendsFilter"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"smoothingIntervals"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C7%2C42%2C2%2C42%2C3%2C43%2C1%2C42%2C3%2C42%2C3%2C43%2C4%2C42%2C3%2C42%2C2%2C42%2C3%2C36%2C0%2C2%2C"run"%2C1%2C2%2C"print"%2C1%2C35%5D%2C"locals"%3A%5B%5B"query"%2C1%2Cfalse%5D%5D%2C"print"%3A%5B%5B%7B"results"%3A%5B%5B%5B"2025-04-23T00%3A00%3A00Z"%2C"2025-04-24T00%3A00%3A00Z"%2C"2025-04-25T00%3A00%3A00Z"%2C"2025-04-26T00%3A00%3A00Z"%2C"2025-04-27T00%3A00%3A00Z"%2C"2025-04-28T00%3A00%3A00Z"%2C"2025-04-29T00%3A00%3A00Z"%2C"2025-04-30T00%3A00%3A00Z"%2C"2025-05-01T00%3A00%3A00Z"%2C"2025-05-02T00%3A00%3A00Z"%2C"2025-05-03T00%3A00%3A00Z"%2C"2025-05-04T00%3A00%3A00Z"%2C"2025-05-05T00%3A00%3A00Z"%2C"2025-05-06T00%3A00%3A00Z"%2C"2025-05-07T00%3A00%3A00Z"%2C"2025-05-08T00%3A00%3A00Z"%2C"2025-05-09T00%3A00%3A00Z"%2C"2025-05-10T00%3A00%3A00Z"%2C"2025-05-11T00%3A00%3A00Z"%2C"2025-05-12T00%3A00%3A00Z"%2C"2025-05-13T00%3A00%3A00Z"%2C"2025-05-14T00%3A00%3A00Z"%2C"2025-05-15T00%3A00%3A00Z"%2C"2025-05-16T00%3A00%3A00Z"%2C"2025-05-17T00%3A00%3A00Z"%2C"2025-05-18T00%3A00%3A00Z"%2C"2025-05-19T00%3A00%3A00Z"%2C"2025-05-20T00%3A00%3A00Z"%2C"2025-05-21T00%3A00%3A00Z"%2C"2025-05-22T00%3A00%3A00Z"%2C"2025-05-23T00%3A00%3A00Z"%2C"2025-05-24T00%3A00%3A00Z"%2C"2025-05-25T00%3A00%3A00Z"%2C"2025-05-26T00%3A00%3A00Z"%2C"2025-05-27T00%3A00%3A00Z"%2C"2025-05-28T00%3A00%3A00Z"%2C"2025-05-29T00%3A00%3A00Z"%2C"2025-05-30T00%3A00%3A00Z"%2C"2025-05-31T00%3A00%3A00Z"%2C"2025-06-01T00%3A00%3A00Z"%2C"2025-06-02T00%3A00%3A00Z"%2C"2025-06-03T00%3A00%3A00Z"%2C"2025-06-04T00%3A00%3A00Z"%2C"2025-06-05T00%3A00%3A00Z"%2C"2025-06-06T00%3A00%3A00Z"%2C"2025-06-07T00%3A00%3A00Z"%2C"2025-06-08T00%3A00%3A00Z"%2C"2025-06-09T00%3A00%3A00Z"%2C"2025-06-10T00%3A00%3A00Z"%2C"2025-06-11T00%3A00%3A00Z"%2C"2025-06-12T00%3A00%3A00Z"%2C"2025-06-13T00%3A00%3A00Z"%2C"2025-06-14T00%3A00%3A00Z"%2C"2025-06-15T00%3A00%3A00Z"%2C"2025-06-16T00%3A00%3A00Z"%2C"2025-06-17T00%3A00%3A00Z"%2C"2025-06-18T00%3A00%3A00Z"%2C"2025-06-19T00%3A00%3A00Z"%2C"2025-06-20T00%3A00%3A00Z"%2C"2025-06-21T00%3A00%3A00Z"%2C"2025-06-22T00%3A00%3A00Z"%2C"2025-06-23T00%3A00%3A00Z"%2C"2025-06-24T00%3A00%3A00Z"%2C"2025-06-25T00%3A00%3A00Z"%2C"2025-06-26T00%3A00%3A00Z"%2C"2025-06-27T00%3A00%3A00Z"%2C"2025-06-28T00%3A00%3A00Z"%2C"2025-06-29T00%3A00%3A00Z"%2C"2025-06-30T00%3A00%3A00Z"%2C"2025-07-01T00%3A00%3A00Z"%2C"2025-07-02T00%3A00%3A00Z"%2C"2025-07-03T00%3A00%3A00Z"%2C"2025-07-04T00%3A00%3A00Z"%2C"2025-07-05T00%3A00%3A00Z"%2C"2025-07-06T00%3A00%3A00Z"%2C"2025-07-07T00%3A00%3A00Z"%2C"2025-07-08T00%3A00%3A00Z"%2C"2025-07-09T00%3A00%3A00Z"%2C"2025-07-10T00%3A00%3A00Z"%2C"2025-07-11T00%3A00%3A00Z"%2C"2025-07-12T00%3A00%3A00Z"%2C"2025-07-13T00%3A00%3A00Z"%2C"2025-07-14T00%3A00%3A00Z"%2C"2025-07-15T00%3A00%3A00Z"%2C"2025-07-16T00%3A00%3A00Z"%2C"2025-07-17T00%3A00%3A00Z"%2C"2025-07-18T00%3A00%3A00Z"%2C"2025-07-19T00%3A00%3A00Z"%2C"2025-07-20T00%3A00%3A00Z"%2C"2025-07-21T00%3A00%3A00Z"%2C"2025-07-22T00%3A00%3A00Z"%5D%2C%5B0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C261%2C120%2C0%2C0%2C0%2C238%2C0%2C0%2C60%2C0%2C0%2C0%2C188%2C49%2C61%2C0%2C0%2C0%2C8%2C0%2C12%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C113%2C315%2C92%2C1080%2C686%2C0%2C0%2C0%2C252%5D%2C%5B0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C37%2C54%2C54%2C54%2C54%2C88%2C88%2C51%2C42%2C42%2C42%2C42%2C35%2C42%2C51%2C42%2C42%2C42%2C43%2C16%2C11%2C2%2C2%2C2%2C2%2C1%2C1%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C0%2C16%2C61%2C74%2C228%2C326%2C326%2C326%2C310%2C301%5D%5D%5D%2C"columns"%3A%5B"date"%2C"total_array"%2C"total"%5D%7D%5D%5D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"__hx_ast"%2C32%2C"SelectQuery"%2C32%2C"select"%2C32%2C"__hx_ast"%2C32%2C"Field"%2C32%2C"chain"%2C32%2C"*"%2C43%2C1%2C42%2C2%2C43%2C1%2C32%2C"select_from"%2C32%2C"__hx_ast"%2C32%2C"JoinExpr"%2C32%2C"table"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"TrendsQuery"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"series"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Array"%2C32%2C"exprs"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"EventsNode"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"event"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"%24pageview"%2C42%2C2%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"math"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"total"%2C42%2C2%2C42%2C3%2C43%2C2%2C42%2C3%2C43%2C1%2C42%2C2%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"dateRange"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"DateRange"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"date_from"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"-90d"%2C42%2C2%2C42%2C3%2C43%2C1%2C42%2C3%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"interval"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C32%2C"day"%2C42%2C2%2C42%2C3%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"trendsFilter"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"HogQLXTag"%2C32%2C"kind"%2C32%2C"TrendsFilter"%2C32%2C"attributes"%2C32%2C"__hx_ast"%2C32%2C"HogQLXAttribute"%2C32%2C"name"%2C32%2C"smoothingIntervals"%2C32%2C"value"%2C32%2C"__hx_ast"%2C32%2C"Constant"%2C32%2C"value"%2C33%2C7%2C42%2C2%2C42%2C3%2C43%2C1%2C42%2C3%2C42%2C3%2C43%2C4%2C42%2C3%2C42%2C2%2C42%2C3%2C36%2C0%2C2%2C"run"%2C1%2C2%2C"print"%2C1%5D%7D%7D%2C"stack"%3A%5B%7B"__hx_ast"%3A"SelectQuery"%2C"select"%3A%5B%7B"__hx_ast"%3A"Field"%2C"chain"%3A%5B"*"%5D%7D%5D%2C"select_from"%3A%7B"__hx_ast"%3A"JoinExpr"%2C"table"%3A%7B"__hx_ast"%3A"HogQLXTag"%2C"kind"%3A"TrendsQuery"%2C"attributes"%3A%5B%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"series"%2C"value"%3A%7B"__hx_ast"%3A"Array"%2C"exprs"%3A%5B%7B"__hx_ast"%3A"HogQLXTag"%2C"kind"%3A"EventsNode"%2C"attributes"%3A%5B%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"event"%2C"value"%3A%7B"__hx_ast"%3A"Constant"%2C"value"%3A"%24pageview"%7D%7D%2C%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"math"%2C"value"%3A%7B"__hx_ast"%3A"Constant"%2C"value"%3A"total"%7D%7D%5D%7D%5D%7D%7D%2C%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"dateRange"%2C"value"%3A%7B"__hx_ast"%3A"HogQLXTag"%2C"kind"%3A"DateRange"%2C"attributes"%3A%5B%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"date_from"%2C"value"%3A%7B"__hx_ast"%3A"Constant"%2C"value"%3A"-90d"%7D%7D%5D%7D%7D%2C%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"interval"%2C"value"%3A%7B"__hx_ast"%3A"Constant"%2C"value"%3A"day"%7D%7D%2C%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"trendsFilter"%2C"value"%3A%7B"__hx_ast"%3A"HogQLXTag"%2C"kind"%3A"TrendsFilter"%2C"attributes"%3A%5B%7B"__hx_ast"%3A"HogQLXAttribute"%2C"name"%3A"smoothingIntervals"%2C"value"%3A%7B"__hx_ast"%3A"Constant"%2C"value"%3A7%7D%7D%5D%7D%7D%5D%7D%7D%7D%2Cnull%5D%2C"upvalues"%3A%5B%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A125%2C"asyncSteps"%3A1%2C"syncDuration"%3A8%2C"maxMemUsed"%3A5823%7D%7D%5D&code=`}
                                buttonProps={{
                                    menuItem: true,
                                }}
                            >
                                Find more...
                            </Link>
                        </DropdownMenuItem>
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function QueryLevelSelector(): JSX.Element | null {
    const { activeModelUri } = useValues(multitabEditorLogic)
    const { updateTab, createTab } = useActions(multitabEditorLogic)

    const activeLevel = activeModelUri?.level || 'new'

    const availableLevels: EditorTabLevel[] = ['new', 'editor', 'source']

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive>
                    {levelIcons[activeLevel] || <IconDatabase />}
                    <strong>{capitalizeFirstLetter(activeLevel)}</strong>
                    <IconChevronRight className="rotate-90 group-data-[state=open]/button-root:rotate-270" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>

            <DropdownMenuContent loop align="start">
                <DropdownMenuLabel>Select level</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {availableLevels.map((level) => (
                    <DropdownMenuItem key={level} asChild>
                        <Link
                            onClick={() => {
                                if (activeModelUri) {
                                    updateTab({ ...activeModelUri, level })
                                } else {
                                    createTab(undefined, undefined, undefined, level)
                                }
                            }}
                            disabled={!availableLevels.includes(level)}
                            buttonProps={{
                                menuItem: true,
                                active: activeLevel === level,
                                disabled: !availableLevels.includes(level),
                            }}
                        >
                            {levelIcons[level] || <IconDatabase />} {capitalizeFirstLetter(level)}
                        </Link>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function NewQuery(): JSX.Element {
    const { treeItemsNew } = useValues(projectTreeDataLogic)
    const { activeModelUri } = useValues(multitabEditorLogic)
    const { setQueryAndLevel, createTab } = useActions(multitabEditorLogic)
    const queryTypes =
        treeItemsNew
            .find(({ name }) => name === 'Insight')
            ?.children?.sort((a, b) => (a.visualOrder ?? 0) - (b.visualOrder ?? 0)) ?? []

    // pastel palette (cycle through)
    const swatches = [
        'bg-sky-500/10 text-sky-700 dark:bg-sky-500/20 dark:text-sky-100',
        'bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-100',
        'bg-violet-500/10 text-violet-700 dark:bg-violet-500/20 dark:text-violet-100',
        'bg-amber-500/10 text-amber-700 dark:bg-amber-500/20 dark:text-amber-100',
        'bg-pink-500/10 text-pink-700 dark:bg-pink-500/20 dark:text-pink-100',
        'bg-stone-500/10 text-stone-700 dark:bg-stone-500/20 dark:text-stone-100',
    ]

    const allQueryTypes = [{ name: 'SQL', icon: <IconDatabase /> }, ...queryTypes]

    const [question, setQuestion] = useState('')
    const handleSubmit = (): void => {}

    return (
        <div className="w-full py-8">
            <div className="w-full text-center pb-4 bg-white dark:bg-black text-sm font-medium">
                Choose an analysis to run or just ask Max.
            </div>

            <div className="flex gap-2 max-w-[800px] m-auto mt-2 mb-4">
                <input
                    type="text"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onClick={() => setQuestion('')}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                    placeholder="How much wood would a woodchuck chuck if a woodchuck could chuck wood?"
                    className="flex-1 px-4 py-3 rounded-lg border border-border dark:border-border-dark bg-white dark:bg-gray-900 text-primary dark:text-primary-dark text-base focus:ring-2 focus:ring-red dark:focus:ring-yellow focus:border-transparent transition-all"
                />
                <LemonButton
                    type="primary"
                    disabledReason={!question.trim() ? 'Please ask a question' : null}
                    onClick={handleSubmit}
                >
                    Ask Max
                </LemonButton>
            </div>

            <div className="w-full overflow-auto p-4 max-w-[1024px] m-auto">
                {/* Fluid grid: auto-fit as many 7rem (112px) boxes as fit, with gap */}
                <div
                    className="grid gap-6"
                    style={{
                        gridTemplateColumns: 'repeat(auto-fit, minmax(7rem, 1fr))',
                    }}
                >
                    {allQueryTypes.map((qt, i) => (
                        <div key={qt.name} className="text-center m-auto">
                            <Link
                                onClick={() => {
                                    const query = sampleQueries[qt.name]
                                    if (query) {
                                        if (!activeModelUri) {
                                            createTab(query.input, undefined, undefined, query.level)
                                        } else {
                                            setQueryAndLevel(query.input, query.level)
                                        }
                                    }
                                }}
                                className="group flex flex-col items-center text-center cursor-pointer select-none focus:outline-none"
                            >
                                <div
                                    className={`flex items-center justify-center w-16 h-16 rounded-xl shadow-sm group-hover:shadow-md transition ${
                                        swatches[i % swatches.length]
                                    }`}
                                >
                                    <span className="text-2xl font-semibold">{qt.icon ?? qt.name[0]}</span>
                                </div>
                                <span className="mt-2 w-full text-xs font-medium truncate px-1 text-primary">
                                    {qt.name}
                                </span>
                            </Link>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
