import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    IconArrowLeft,
    IconAsterisk,
    IconBinary,
    IconBrackets,
    IconCalculator,
    IconCalendar,
    IconClock,
    IconExpand45,
    IconFilter,
    IconLetter,
    IconList,
    IconPlay,
    IconQuestion,
    IconStack,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonInput,
    LemonSegmentedButton,
    LemonTable,
    LemonTag,
    LemonTextArea,
    Link,
    Popover,
    Spinner,
} from '@posthog/lemon-ui'

import { ResizableElement } from 'lib/components/ResizeElement/ResizeElement'
import { SearchAutocomplete } from 'lib/components/SearchAutocomplete/SearchAutocomplete'
import { useChart } from 'lib/hooks/useChart'
import { ClampedText } from 'lib/lemon-ui/ClampedText'
import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { humanFriendlyNumber } from 'lib/utils'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { SceneExport } from '../sceneTypes'
import { Scene } from '../sceneTypes'
import { urls } from '../urls'
import {
    BIAggregation,
    BIQueryColumn,
    BIQueryFilter,
    BISchemaVersion,
    BISortDirection,
    BITimeAggregation,
    FieldTreeNode,
    biLogic,
    buildCreateTableStatement,
    columnAlias,
    columnKey,
    defaultColumnForTable,
    getDatabaseNameFromTableName,
    getTableDialect,
    getTableSourceId,
    isDirectQueryTable,
    isJsonField,
} from './biLogic'

const COLORS = ['#5375ff', '#ff7a9e', '#2bc4ff', '#f6a700', '#7a49ff']

const DEFAULT_CHART_HEIGHT = 250
const MIN_RESIZABLE_HEIGHT = 140
const MIN_SIDEBAR_WIDTH = 240
const MIN_MAIN_WIDTH = 360
const MAX_COLUMN_WIDTH = 320
const MAX_CELL_LINES = 6
const MIN_CHARS_TO_CLAMP = 120

type QueryPreviewLanguage = 'hogql' | 'clickhouse' | 'postgres'

export function formatFilter(filter: BIQueryFilter): JSX.Element {
    return (
        <LemonTag type="primary" key={columnKey(filter.column)}>
            {columnAlias(filter.column)} {filter.expression}
        </LemonTag>
    )
}

function dedupeColumns(columns: BIQueryColumn[]): BIQueryColumn[] {
    const seen = new Set<string>()

    return columns.filter((column) => {
        const key = columnKey(column)
        if (seen.has(key)) {
            return false
        }
        seen.add(key)
        return true
    })
}

function flattenFieldNodes(
    nodes: FieldTreeNode[],
    includeNestedChildren = true
): Array<{ path: string; field: DatabaseSchemaField }> {
    return nodes.flatMap((node) => {
        if (!node.hasChildren || isJsonField(node.field)) {
            return { path: node.path, field: node.field }
        }

        if (!includeNestedChildren) {
            return []
        }

        return flattenFieldNodes(node.children, includeNestedChildren)
    })
}

function FieldTree({
    nodes,
    searchTerm,
    selectedColumns,
    tableName,
    expandedFields,
    onSetExpandedFields,
    onSelect,
}: {
    nodes: FieldTreeNode[]
    searchTerm: string
    selectedColumns: BIQueryColumn[]
    tableName: string
    expandedFields: string[]
    onSetExpandedFields: (paths: string[]) => void
    onSelect: (path: string, field?: DatabaseSchemaField) => void
}): JSX.Element {
    const [openJsonPopover, setOpenJsonPopover] = useState<string | null>(null)
    const [jsonPathDraft, setJsonPathDraft] = useState('')
    const jsonTextAreaRef = useRef<HTMLTextAreaElement | null>(null)

    const fieldTreeData = useMemo<TreeDataItem[]>(() => {
        const selectionsByField = selectedColumns.reduce((acc, column) => {
            if (column.table !== tableName) {
                return acc
            }

            const key = column.field
            const current = acc.get(key) || []
            acc.set(key, [...current, column])
            return acc
        }, new Map<string, BIQueryColumn[]>())

        const buildTree = (treeNodes: FieldTreeNode[]): TreeDataItem[] =>
            treeNodes.map((node) => {
                const isJson = isJsonField(node.field)
                const hasChildren = node.hasChildren && !isJson

                const selectedAggregations = selectionsByField.get(node.path)
                const aggregationBadges = Array.from(
                    new Set(
                        (selectedAggregations || [])
                            .map((column) => column.aggregation)
                            .filter(Boolean) as BIAggregation[]
                    )
                )
                const isSelected = Boolean(selectedAggregations?.length)

                const label = (
                    <div className="flex items-center gap-1">
                        <span
                            className={clsx({
                                underline: isSelected,
                            })}
                        >
                            <SearchHighlightMultiple string={node.field.name} substring={searchTerm} />
                        </span>
                        {aggregationBadges.map((aggregation) => (
                            <LemonTag key={aggregation} type="primary" size="small">
                                {aggregation.toUpperCase()}
                            </LemonTag>
                        ))}
                    </div>
                )

                return {
                    id: node.path,
                    name: node.field.name,
                    displayName: label,
                    record: { ...node, isJson, hasChildren, type: hasChildren ? 'folder' : 'node' },
                    icon: hasChildren ? undefined : fieldTypeIcon(node.field),
                    children: hasChildren ? buildTree(node.children) : undefined,
                }
            })

        return buildTree(nodes)
    }, [nodes, searchTerm, selectedColumns, tableName])

    const focusJsonTextArea = (): void => {
        requestAnimationFrame(() => {
            const textArea = jsonTextAreaRef.current
            if (textArea) {
                const length = textArea.value.length
                textArea.focus()
                textArea.setSelectionRange(length, length)
                textArea.scrollTop = textArea.scrollHeight
            }
        })
    }

    const closeJsonPopover = (): void => {
        setOpenJsonPopover(null)
        setJsonPathDraft('')
    }

    useEffect(() => {
        if (openJsonPopover) {
            focusJsonTextArea()
        }
    }, [openJsonPopover])

    const handleJsonSubmit = (path: string, field?: DatabaseSchemaField): void => {
        const selectedPath = jsonPathDraft.trim() || path
        onSelect(selectedPath, field)
        setJsonPathDraft('')
        setOpenJsonPopover(null)
    }

    return (
        <LemonTree
            data={fieldTreeData}
            expandedItemIds={expandedFields}
            onSetExpandedItemIds={onSetExpandedFields}
            onItemClick={(item, event) => {
                const record = item?.record as (FieldTreeNode & { isJson?: boolean; hasChildren?: boolean }) | undefined

                if (!record) {
                    return
                }

                if (record.isJson) {
                    event.stopPropagation()
                    setOpenJsonPopover(record.path)
                    setJsonPathDraft(record.path)
                    return
                }

                if (record.hasChildren) {
                    const currentlyExpanded = expandedFields.includes(record.path)
                    const updatedExpansion = currentlyExpanded
                        ? expandedFields.filter((id) => id !== record.path)
                        : [...expandedFields, record.path]

                    onSetExpandedFields(updatedExpansion)
                    return
                }

                onSelect(record.path, record.field)
            }}
            renderItem={(item, children) => {
                const record = item.record as (FieldTreeNode & { isJson?: boolean }) | undefined

                if (!record?.isJson) {
                    return children
                }

                return (
                    <Popover
                        visible={openJsonPopover === record.path}
                        onVisibilityChange={(visible) => {
                            setOpenJsonPopover(visible ? record.path : null)
                            setJsonPathDraft(visible ? record.path : '')
                            if (visible) {
                                focusJsonTextArea()
                            }
                        }}
                        onClickOutside={closeJsonPopover}
                        overlay={
                            <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                                <div className="text-muted">Add column or nested field</div>
                                <div className="text-muted">e.g. properties.$browser</div>
                                <LemonTextArea
                                    ref={jsonTextAreaRef}
                                    value={jsonPathDraft}
                                    minRows={1}
                                    onChange={(value) => setJsonPathDraft((value || '').trim())}
                                    onFocus={focusJsonTextArea}
                                    autoFocus
                                    onKeyDown={(event) => {
                                        if (event.key === 'Enter' && !event.shiftKey) {
                                            event.preventDefault()
                                            handleJsonSubmit(record.path, record.field)
                                        }
                                    }}
                                />
                                <LemonButton
                                    type="primary"
                                    onClick={(event) => {
                                        event.stopPropagation()
                                        handleJsonSubmit(record.path, record.field)
                                    }}
                                    fullWidth
                                >
                                    Add column
                                </LemonButton>
                            </div>
                        }
                    >
                        <span className="w-full">{children}</span>
                    </Popover>
                )
            }}
        />
    )
}

export const scene: SceneExport = {
    component: BIScene,
    logic: biLogic,
    scene: Scene.BI,
}

export function BIScene(): JSX.Element {
    const {
        filteredTables,
        selectedFieldTrees,
        selectedTableObject,
        selectedFields,
        selectedColumns,
        queryResponse,
        queryResponseLoading,
        filters,
        queryString,
        _queryString,
        limit,
        searchTerm,
        databaseLoading,
        sort,
        expandedFields,
        schemaEditor,
        schemaEditorTables,
        schemaEditorTable,
        schemaEditorDraft,
        schemaEditorVersionHistory,
    } = useValues(biLogic)
    const {
        addColumn,
        setColumnAggregation,
        setColumnTimeInterval,
        selectTable,
        removeColumn,
        addFilter,
        updateFilter,
        removeFilter,
        setTableSearchTerm,
        setColumnSearchTerm,
        setColumns,
        setLimit,
        setSort,
        refreshQuery,
        resetSelection,
        setExpandedFields,
        openSchemaEditor,
        closeSchemaEditor,
        selectSchemaTableForEditing,
        setSchemaDraft,
        saveSchemaDraft,
    } = useActions(biLogic)

    const queryDialect: 'clickhouse' | 'postgres' = selectedTableObject
        ? getTableDialect(selectedTableObject)
        : 'clickhouse'

    const [openColumnPopover, setOpenColumnPopover] = useState<string | null>(null)
    const [openFilterPopover, setOpenFilterPopover] = useState<number | null>(null)
    const [showGeneratedQuery, setShowGeneratedQuery] = useState(false)
    const [queryPreviewLanguage, setQueryPreviewLanguage] = useState<QueryPreviewLanguage>('hogql')
    const [chartType, setChartType] = useState<'pie' | 'line' | 'bar' | 'area'>('pie')
    const [expandedTableGroups, setExpandedTableGroups] = useState<string[]>(['folder-posthog'])
    const [viewportWidth, setViewportWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 1440)
    const [viewportHeight, setViewportHeight] = useState(typeof window !== 'undefined' ? window.innerHeight : 900)
    const [sidebarWidth, setSidebarWidth] = useState(() =>
        Math.min(
            320,
            Math.max(MIN_SIDEBAR_WIDTH, (typeof window !== 'undefined' ? window.innerWidth : 1440) - MIN_MAIN_WIDTH)
        )
    )
    const [chartHeight, setChartHeight] = useState(DEFAULT_CHART_HEIGHT)
    const [queryPreviewHeight, setQueryPreviewHeight] = useState(180)
    const databaseSideAction = useCallback(
        (item: TreeDataItem) => {
            if (item.record?.type !== 'folder') {
                return null
            }

            const databaseName = item.record?.databaseName || item.name

            return (
                <div className="flex flex-col gap-1 p-1">
                    <LemonButton type="tetriary" size="small" fullWidth disabled>
                        Edit connection
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        fullWidth
                        onClick={(event) => {
                            event.stopPropagation()
                            openSchemaEditor(databaseName)
                        }}
                    >
                        Modify schema
                    </LemonButton>
                </div>
            )
        },
        [openSchemaEditor]
    )

    const tableTreeData = useMemo<TreeDataItem[]>(() => {
        const groupedTables: Record<string, TreeDataItem> = {}

        filteredTables.forEach((table) => {
            const folderName = getDatabaseNameFromTableName(table.name)
            const tableName = table.name.includes('.') ? table.name.split('.').slice(1).join('.') : table.name

            if (!groupedTables[folderName]) {
                groupedTables[folderName] = {
                    id: `folder-${folderName}`,
                    name: folderName,
                    displayName: <SearchHighlightMultiple string={folderName} substring={searchTerm} />,
                    type: 'node',
                    record: { type: 'folder', databaseName: folderName },
                    children: [],
                    icon: <IconStack />,
                }
            }

            groupedTables[folderName].children?.push({
                id: `table-${table.name}`,
                name: tableName,
                displayName: <SearchHighlightMultiple string={tableName} substring={searchTerm} />,
                type: 'node',
                record: { type: 'table', tableName: table.name },
                icon: <IconStack />,
            })
        })

        return Object.values(groupedTables)
            .sort((a, b) => {
                if (a.name === 'posthog') {
                    return -1
                }
                if (b.name === 'posthog') {
                    return 1
                }
                return a.name.localeCompare(b.name)
            })
            .map((group) => ({
                ...group,
                children: (group.children || []).sort((a, b) => a.name.localeCompare(b.name)),
            }))
    }, [filteredTables, searchTerm])

    useEffect(() => {
        if (typeof window === 'undefined') {
            return
        }

        const handleResize = (): void => {
            setViewportWidth(window.innerWidth)
            setViewportHeight(window.innerHeight)

            setSidebarWidth((current) =>
                Math.min(
                    Math.max(current, MIN_SIDEBAR_WIDTH),
                    Math.max(MIN_SIDEBAR_WIDTH, window.innerWidth - MIN_MAIN_WIDTH)
                )
            )

            setChartHeight((current) =>
                Math.min(
                    Math.max(current, MIN_RESIZABLE_HEIGHT),
                    Math.max(MIN_RESIZABLE_HEIGHT, window.innerHeight - 240)
                )
            )

            setQueryPreviewHeight((current) =>
                Math.min(
                    Math.max(current, MIN_RESIZABLE_HEIGHT),
                    Math.max(MIN_RESIZABLE_HEIGHT, window.innerHeight - 260)
                )
            )
        }

        handleResize()
        window.addEventListener('resize', handleResize)

        return () => {
            window.removeEventListener('resize', handleResize)
        }
    }, [])

    useEffect(() => {
        const groupIds = tableTreeData.map((group) => group.id)
        setExpandedTableGroups((current) => {
            const preserved = current.filter((id) => groupIds.includes(id))
            const missing = groupIds.filter((id) => !preserved.includes(id))
            return [...preserved, ...missing]
        })
    }, [tableTreeData])

    useEffect(() => {
        if (!_queryString) {
            setShowGeneratedQuery(false)
            setQueryPreviewLanguage('hogql')
        }
    }, [_queryString])

    useEffect(() => {
        setQueryPreviewLanguage((current) => {
            if (queryDialect === 'postgres' && current === 'clickhouse') {
                return 'hogql'
            }
            if (queryDialect === 'clickhouse' && current === 'postgres') {
                return 'hogql'
            }
            return current
        })
    }, [queryDialect])

    const rawRows = useMemo(() => {
        if (!queryResponse?.results || selectedFields.length === 0) {
            return []
        }

        const headers = queryResponse.columns as { name: string }[] | undefined
        return queryResponse.results.map((row: any[]) => {
            const asObject: Record<string, any> = {}
            row.forEach((value, index) => {
                const name = headers?.[index]?.name || selectedFields[index]?.alias || `col_${index}`
                asObject[name] = value
            })
            return asObject
        })
    }, [queryResponse, selectedFields])

    const rows = useMemo(() => rawRows.slice(0, limit), [rawRows, limit])
    const hasMoreRows = rawRows.length > rows.length

    const numericColumns = useMemo(() => {
        if (rows.length === 0) {
            return []
        }
        const keys = Object.keys(rows[0] || {})
        return keys.filter((key) => rows.some((row) => typeof row[key] === 'number'))
    }, [rows])

    const timeColumns = useMemo(() => {
        if (rows.length === 0) {
            return []
        }
        const keys = Object.keys(rows[0] || {})
        return keys.filter((key) => {
            const value = rows[0]?.[key]
            return typeof value === 'string' && /\d{4}-\d{2}-\d{2}/.test(value)
        })
    }, [rows])

    const isTimeSeries = timeColumns.length > 0

    useEffect(() => {
        if (isTimeSeries && chartType === 'pie') {
            setChartType('line')
        }
    }, [chartType, isTimeSeries])

    const effectiveChartType: 'pie' | 'line' | 'bar' | 'area' = isTimeSeries && chartType === 'pie' ? 'line' : chartType

    const chartData = useMemo(() => {
        if (numericColumns.length === 0 || rows.length === 0) {
            return null
        }

        const valueKey = numericColumns[0]

        if (isTimeSeries) {
            const timeKey = timeColumns[0]
            if (!timeKey) {
                return null
            }

            return {
                labels: rows.map((row) => String(row[timeKey] ?? '')),
                values: rows.map((row) => Number(row[valueKey]) || 0),
                labelKey: timeKey,
                valueKey,
            }
        }

        const labelKey =
            Object.keys(rows[0] || {}).find(
                (key) => key !== valueKey && !timeColumns.includes(key) && typeof rows[0]?.[key] !== 'number'
            ) || Object.keys(rows[0] || {})[0]

        return {
            labels: rows.map((row, index) => {
                const value = row[labelKey]
                if (value === undefined || value === null || value === '') {
                    return `Row ${index + 1}`
                }
                return String(value)
            }),
            values: rows.map((row) => Number(row[valueKey]) || 0),
            labelKey,
            valueKey,
        }
    }, [numericColumns, rows, timeColumns, isTimeSeries])

    const availableChartTypes: Array<'pie' | 'line' | 'bar' | 'area'> = isTimeSeries
        ? ['line', 'bar', 'area']
        : ['pie', 'line', 'bar', 'area']

    const queryPreviewOptions = useMemo(
        () =>
            queryDialect === 'postgres'
                ? [
                      { value: 'hogql' as const, label: 'HogQL' },
                      { value: 'postgres' as const, label: 'Postgres' },
                  ]
                : [
                      { value: 'hogql' as const, label: 'HogQL' },
                      { value: 'clickhouse' as const, label: 'ClickHouse' },
                  ],
        [queryDialect]
    )

    const activeQueryPreviewLanguage = queryPreviewOptions.some((option) => option.value === queryPreviewLanguage)
        ? queryPreviewLanguage
        : 'hogql'

    const displayedQuery = useMemo(() => {
        if (activeQueryPreviewLanguage === 'hogql') {
            return queryString
        }

        const sqlQuery = activeQueryPreviewLanguage === 'postgres' ? queryResponse?.postgres : queryResponse?.clickhouse

        if (sqlQuery) {
            return sqlQuery
        }

        if (queryResponseLoading) {
            return 'Loading SQL…'
        }

        return activeQueryPreviewLanguage === 'postgres'
            ? 'Postgres SQL will appear after running the query.'
            : 'ClickHouse SQL will appear after running the query.'
    }, [
        activeQueryPreviewLanguage,
        queryResponse?.clickhouse,
        queryResponse?.postgres,
        queryResponseLoading,
        queryString,
    ])

    const { openInSqlEditorQuery, openInSqlEditorDisabledReason } = useMemo((): {
        openInSqlEditorQuery: string | null
        openInSqlEditorDisabledReason: string | null
    } => {
        const sourceId = selectedTableObject ? getTableSourceId(selectedTableObject) : null
        const directQueryTable = selectedTableObject ? isDirectQueryTable(selectedTableObject) : false

        if (activeQueryPreviewLanguage === 'clickhouse') {
            return {
                openInSqlEditorQuery: null,
                openInSqlEditorDisabledReason: "can't query clickhouse directly",
            }
        }

        if (activeQueryPreviewLanguage === 'postgres') {
            if (!queryResponse?.postgres) {
                return {
                    openInSqlEditorQuery: null,
                    openInSqlEditorDisabledReason: queryResponseLoading
                        ? 'Loading SQL…'
                        : 'Run the query to view Postgres SQL',
                }
            }

            const directive = sourceId ? `--direct:${sourceId}` : '--direct'
            return {
                openInSqlEditorQuery: `${directive}\n${queryResponse.postgres}`,
                openInSqlEditorDisabledReason: null,
            }
        }

        if (!queryString) {
            return { openInSqlEditorQuery: null, openInSqlEditorDisabledReason: null }
        }

        if (queryDialect === 'postgres') {
            if (directQueryTable && sourceId) {
                return {
                    openInSqlEditorQuery: `--pg:${sourceId}\n${queryString}`,
                    openInSqlEditorDisabledReason: null,
                }
            }
            return { openInSqlEditorQuery: `--pg\n${queryString}`, openInSqlEditorDisabledReason: null }
        }

        return { openInSqlEditorQuery: queryString, openInSqlEditorDisabledReason: null }
    }, [
        activeQueryPreviewLanguage,
        queryDialect,
        queryResponse?.postgres,
        queryResponseLoading,
        queryString,
        selectedTableObject,
    ])

    const maxSidebarWidth = Math.max(MIN_SIDEBAR_WIDTH, viewportWidth - MIN_MAIN_WIDTH)
    const maxChartHeight = Math.max(MIN_RESIZABLE_HEIGHT, viewportHeight - 240)
    const maxQueryPreviewHeight = Math.max(MIN_RESIZABLE_HEIGHT, viewportHeight - 260)

    const { canvasRef: chartCanvasRef } = useChart({
        getConfig: () => {
            if (!chartData || chartData.values.length === 0) {
                return null
            }

            const baseChartType = effectiveChartType === 'area' ? 'line' : effectiveChartType
            const datasetColor = COLORS[0]
            const pieColors = chartData.labels.map((_, index) => COLORS[index % COLORS.length])

            return {
                type: baseChartType,
                data: {
                    labels: chartData.labels,
                    datasets: [
                        {
                            label: chartData.valueKey,
                            data: chartData.values,
                            backgroundColor: baseChartType === 'pie' ? pieColors : `${datasetColor}33`,
                            borderColor: datasetColor,
                            borderWidth: 2,
                            fill: effectiveChartType === 'area',
                            tension: 0.2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'bottom',
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    const label = context.label ? `${context.label}: ` : ''
                                    return `${label}${context.formattedValue}`
                                },
                            },
                        },
                    },
                    scales:
                        baseChartType === 'pie'
                            ? undefined
                            : {
                                  x: {
                                      ticks: {
                                          maxRotation: 45,
                                          minRotation: 0,
                                          autoSkip: true,
                                      },
                                      title: {
                                          display: true,
                                          text: chartData.labelKey,
                                      },
                                  },
                                  y: {
                                      beginAtZero: true,
                                      title: {
                                          display: true,
                                          text: chartData.valueKey,
                                      },
                                  },
                              },
                },
            }
        },
        deps: [chartData, effectiveChartType],
    })

    const closePopovers = (): void => {
        setOpenColumnPopover(null)
        setOpenFilterPopover(null)
    }

    const allTableColumns: BIQueryColumn[] = useMemo(() => {
        if (!selectedTableObject) {
            return []
        }

        return flattenFieldNodes(selectedFieldTrees, false).map(({ path, field }) => ({
            table: selectedTableObject.name,
            field: path,
            ...(field && isTemporalField(field) ? { timeInterval: 'day' as BITimeAggregation } : {}),
        }))
    }, [selectedFieldTrees, selectedTableObject])

    const allColumnsSelected = useMemo(() => {
        if (!selectedTableObject || allTableColumns.length === 0) {
            return false
        }

        const selectedFieldNames = new Set(
            selectedColumns.filter((column) => column.table === selectedTableObject.name).map((column) => column.field)
        )

        return allTableColumns.every((column) => selectedFieldNames.has(column.field))
    }, [allTableColumns, selectedColumns, selectedTableObject])

    const addAllColumnsToQuery = (): void => {
        if (!selectedTableObject) {
            return
        }

        if (allColumnsSelected) {
            const defaultColumn = defaultColumnForTable(selectedTableObject)

            if (defaultColumn) {
                setColumns([defaultColumn])
            }

            return
        }

        if (allTableColumns.length === 0) {
            return
        }

        setColumns(dedupeColumns(allTableColumns))
    }

    const startVerticalResize = (
        event: React.MouseEvent | React.TouchEvent,
        initialHeight: number,
        setHeight: (height: number) => void,
        minHeight: number,
        maxHeight: number
    ): void => {
        event.preventDefault()

        const startY = 'touches' in event ? event.touches[0].clientY : event.clientY
        const clampHeight = (height: number): number => Math.min(Math.max(height, minHeight), maxHeight)

        const handleMove = (moveEvent: MouseEvent | TouchEvent): void => {
            const clientY = 'touches' in moveEvent ? moveEvent.touches[0].clientY : moveEvent.clientY
            const deltaY = clientY - startY

            setHeight(clampHeight(initialHeight + deltaY))
        }

        const stopResize = (): void => {
            document.removeEventListener('mousemove', handleMove)
            document.removeEventListener('mouseup', stopResize)
            document.removeEventListener('touchmove', handleMove)
            document.removeEventListener('touchend', stopResize)
            document.body.classList.remove('is-resizing')
        }

        document.body.classList.add('is-resizing')
        document.addEventListener('mousemove', handleMove)
        document.addEventListener('mouseup', stopResize)
        document.addEventListener('touchmove', handleMove)
        document.addEventListener('touchend', stopResize)
    }

    const startChartResize = (event: React.MouseEvent | React.TouchEvent): void =>
        startVerticalResize(event, chartHeight, setChartHeight, MIN_RESIZABLE_HEIGHT, maxChartHeight)

    const startQueryPreviewResize = (event: React.MouseEvent | React.TouchEvent): void =>
        startVerticalResize(
            event,
            queryPreviewHeight,
            setQueryPreviewHeight,
            MIN_RESIZABLE_HEIGHT,
            maxQueryPreviewHeight
        )

    const ResizeHandle = ({
        onStart,
        ariaLabel,
    }: {
        onStart: (event: React.MouseEvent | React.TouchEvent) => void
        ariaLabel: string
    }): JSX.Element => (
        <div
            className="h-2 cursor-row-resize -mx-1 rounded-sm bg-[var(--border)] hover:bg-accent-highlight-primary"
            role="separator"
            aria-label={ariaLabel}
            onMouseDown={onStart}
            onTouchStart={onStart}
        />
    )

    if (schemaEditor.databaseName) {
        return (
            <SchemaEditorView
                databaseName={schemaEditor.databaseName}
                tables={schemaEditorTables}
                selectedTable={schemaEditorTable}
                draft={schemaEditorDraft}
                versions={schemaEditorVersionHistory}
                onClose={closeSchemaEditor}
                onSelectTable={selectSchemaTableForEditing}
                onChangeDraft={(tableName, draft) => setSchemaDraft(tableName, draft)}
                onSave={(tableName, draft) => saveSchemaDraft(tableName, draft)}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4 h-full" onClick={closePopovers}>
            <div className="flex gap-1 h-full min-h-0">
                <ResizableElement
                    defaultWidth={sidebarWidth}
                    minWidth={MIN_SIDEBAR_WIDTH}
                    maxWidth={maxSidebarWidth}
                    onResize={setSidebarWidth}
                    className="shrink-0 h-full min-h-0"
                    style={{ width: Math.min(sidebarWidth, maxSidebarWidth) }}
                >
                    <div className="h-full min-h-0 flex flex-col pr-2">
                        <div className="flex items-center gap-1 mb-2">
                            {selectedTableObject && (
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    icon={<IconArrowLeft />}
                                    onClick={() => resetSelection()}
                                />
                            )}
                            <SearchAutocomplete
                                inputPlaceholder={selectedTableObject ? 'Search columns' : 'Search tables'}
                                value={searchTerm}
                                onChange={(value) =>
                                    selectedTableObject ? setColumnSearchTerm(value) : setTableSearchTerm(value)
                                }
                                onClear={() => (selectedTableObject ? setColumnSearchTerm('') : setTableSearchTerm(''))}
                            />
                        </div>
                        <div className="flex-1 overflow-y-auto">
                            {selectedTableObject ? (
                                <>
                                    <div className="flex items-start justify-between gap-2 px-1">
                                        <div>
                                            <div className="font-semibold">{selectedTableObject.name}</div>
                                            {selectedTableObject?.source?.source_type === 'Postgres' ? (
                                                <div className="text-xs text-muted">via postgres direct connection</div>
                                            ) : (
                                                <div className="text-xs text-muted">via posthog data warehouse</div>
                                            )}
                                        </div>
                                        {selectedFieldTrees.length > 0 && (
                                            <LemonButton
                                                size="xsmall"
                                                type="secondary"
                                                icon={<IconAsterisk />}
                                                onClick={addAllColumnsToQuery}
                                                tooltip={<>Select all columns</>}
                                                active={allColumnsSelected}
                                            />
                                        )}
                                    </div>
                                    {selectedFieldTrees.length > 0 ? (
                                        <FieldTree
                                            nodes={selectedFieldTrees}
                                            searchTerm={searchTerm}
                                            selectedColumns={selectedColumns}
                                            tableName={selectedTableObject.name}
                                            expandedFields={expandedFields}
                                            onSetExpandedFields={setExpandedFields}
                                            onSelect={(path, field) => {
                                                const matchingColumns = selectedColumns.filter(
                                                    (selectedColumn) =>
                                                        selectedColumn.table === selectedTableObject.name &&
                                                        selectedColumn.field === path
                                                )

                                                if (matchingColumns.length > 0) {
                                                    matchingColumns.forEach((matchingColumn) =>
                                                        removeColumn(matchingColumn)
                                                    )
                                                    return
                                                }

                                                const column = {
                                                    table: selectedTableObject.name,
                                                    field: path,
                                                    ...(field && isTemporalField(field) ? { timeInterval: 'day' } : {}),
                                                }

                                                addColumn(column)
                                            }}
                                        />
                                    ) : (
                                        <div className="text-muted">No columns match your search.</div>
                                    )}
                                </>
                            ) : databaseLoading ? (
                                <div className="flex items-center gap-2 text-muted">
                                    <Spinner />
                                    Loading tables…
                                </div>
                            ) : tableTreeData.length > 0 ? (
                                <LemonTree
                                    data={tableTreeData}
                                    expandedItemIds={expandedTableGroups}
                                    onSetExpandedItemIds={setExpandedTableGroups}
                                    itemSideAction={databaseSideAction}
                                    onItemClick={(item) => {
                                        if (item.record?.type === 'table') {
                                            selectTable(item.record.tableName)
                                        }
                                    }}
                                />
                            ) : (
                                <div className="text-muted">No tables match your search.</div>
                            )}
                        </div>
                    </div>
                </ResizableElement>

                <div className="flex-1 flex flex-col gap-2 min-h-0 min-w-0">
                    <div className="flex items-center justify-between gap-2 w-full">
                        <div className="flex items-center gap-2">
                            <LemonButton type="secondary" onClick={() => refreshQuery()} icon={<IconPlay />}>
                                Run query
                            </LemonButton>
                            <LemonInput
                                type="number"
                                min={1}
                                value={limit}
                                onChange={(value) => setLimit(Number(value) || 50)}
                                suffix="rows"
                                style={{ width: 70 }}
                            />
                            <div className="flex flex-wrap gap-2">
                                {filters.map((filter, index) => (
                                    <FilterPill
                                        key={`${columnKey(filter.column)}-${index}`}
                                        filter={filter}
                                        isOpen={openFilterPopover === index}
                                        onOpenChange={(visible) => {
                                            setOpenColumnPopover(null)
                                            setOpenFilterPopover(visible ? index : null)
                                        }}
                                        onUpdate={(expression) => updateFilter(index, expression)}
                                        onRemove={() => removeFilter(index)}
                                    />
                                ))}
                            </div>{' '}
                        </div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => setShowGeneratedQuery((current) => !current)}
                            disabled={!_queryString}
                        >
                            {showGeneratedQuery ? 'Hide SQL' : 'Show SQL'}
                        </LemonButton>
                    </div>

                    {showGeneratedQuery && _queryString && (
                        <LemonCard
                            hoverEffect={false}
                            className="flex flex-col overflow-hidden p-4"
                            style={{
                                minHeight: MIN_RESIZABLE_HEIGHT,
                                height: queryPreviewHeight,
                                maxHeight: maxQueryPreviewHeight,
                            }}
                        >
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <LemonSegmentedButton
                                    size="xsmall"
                                    value={activeQueryPreviewLanguage}
                                    onChange={(value) => setQueryPreviewLanguage(value)}
                                    options={queryPreviewOptions}
                                />
                                <div className="flex items-center gap-2">
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconExpand45 />}
                                        disabled={!openInSqlEditorQuery}
                                        onClick={() =>
                                            openInSqlEditorQuery && newInternalTab(urls.sqlEditor(openInSqlEditorQuery))
                                        }
                                        tooltip={openInSqlEditorDisabledReason || 'Open in SQL editor'}
                                    />
                                </div>
                            </div>
                            <pre className="flex-1 overflow-auto whitespace-pre-wrap text-xs mb-0">
                                {(displayedQuery || '').trim()}
                            </pre>
                        </LemonCard>
                    )}

                    {showGeneratedQuery && _queryString && numericColumns.length > 0 && (
                        <ResizeHandle onStart={startQueryPreviewResize} ariaLabel="Resize generated query" />
                    )}

                    {numericColumns.length > 0 && selectedFields.length > 0 && (
                        <LemonCard
                            hoverEffect={false}
                            className="relative flex flex-col overflow-hidden p-4"
                            style={{ minHeight: MIN_RESIZABLE_HEIGHT, height: chartHeight, maxHeight: maxChartHeight }}
                        >
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <div>
                                    <div className="text-muted">
                                        {isTimeSeries
                                            ? `${chartData?.valueKey || numericColumns[0]} over ${chartData?.labelKey || timeColumns[0]}`
                                            : `${effectiveChartType === 'pie' ? 'Share of' : 'Chart of'} ${chartData?.valueKey || numericColumns[0]}`}
                                    </div>
                                    {chartData && (
                                        <div className="text-2xl font-semibold">
                                            {humanFriendlyNumber(chartData.values.reduce((acc, cur) => acc + cur, 0))}
                                        </div>
                                    )}
                                </div>
                                <LemonSegmentedButton
                                    value={effectiveChartType}
                                    onChange={(value) => setChartType(value)}
                                    options={availableChartTypes.map((type) => ({
                                        value: type,
                                        label: type === 'area' ? 'Area' : type.charAt(0).toUpperCase() + type.slice(1),
                                    }))}
                                />
                            </div>
                            <div className="mt-2 flex-1 min-h-0">
                                {chartData && chartData.values.length > 0 ? (
                                    <div className="w-full h-full">
                                        <canvas ref={chartCanvasRef} className="w-full h-full" />
                                    </div>
                                ) : (
                                    <div className="text-muted">Add columns to see a chart.</div>
                                )}
                            </div>

                            {queryResponseLoading && (
                                <div className="absolute inset-0 bg-bg-3000/70 backdrop-blur-xs flex items-center justify-center">
                                    <Spinner />
                                </div>
                            )}
                        </LemonCard>
                    )}

                    {numericColumns.length > 0 && selectedFields.length > 0 && (
                        <ResizeHandle onStart={startChartResize} ariaLabel="Resize chart" />
                    )}

                    <LemonCard className="flex-1 min-h-0 flex flex-col min-w-full max-w-full p-4" hoverEffect={false}>
                        {selectedFields.length === 0 ? (
                            <div className="deprecated-space-y-4">
                                <LemonBanner type="info">
                                    This is a flagged feature <code>data-explorer</code>. Share your feedback with
                                    #team-data-stack.
                                </LemonBanner>
                                <div className="text-muted">
                                    <p className="font-bold">Select a table from the left.</p>
                                    <p>You will then be able to query it and all the relations within reach.</p>
                                    <p>
                                        Manage your <Link to={urls.dataPipelines('sources')}>data sources here</Link>.
                                    </p>
                                    <p>
                                        Add a new{' '}
                                        <Link to={urls.dataWarehouseSourceNew('postgres')}>postgres direct query</Link>{' '}
                                        source. You must manually select "Direct query mode".
                                    </p>
                                </div>
                            </div>
                        ) : (
                            <div className="flex-1 min-h-0 flex flex-col max-w-full">
                                <div className="flex-1 min-h-0 overflow-auto">
                                    <LemonTable
                                        dataSource={rows}
                                        loading={queryResponseLoading && selectedFields.length > 0}
                                        columns={selectedFields.map(({ column, field, alias }) => ({
                                            title: (
                                                <ColumnHeader
                                                    column={column}
                                                    alias={alias}
                                                    field={field}
                                                    onRemove={() => removeColumn(column)}
                                                    onAddFilter={(expression) =>
                                                        addFilter({ column, expression: expression || '= ""' })
                                                    }
                                                    sortDirection={
                                                        sort && columnKey(sort.column) === columnKey(column)
                                                            ? sort.direction
                                                            : null
                                                    }
                                                    onSort={(direction) => setSort(column, direction)}
                                                    onSetAggregation={(aggregation) =>
                                                        setColumnAggregation(
                                                            column,
                                                            aggregation === column.aggregation ? null : aggregation
                                                        )
                                                    }
                                                    onSetTimeInterval={(timeInterval) =>
                                                        setColumnTimeInterval(
                                                            column,
                                                            timeInterval === column.timeInterval ? null : timeInterval
                                                        )
                                                    }
                                                    isPopoverOpen={openColumnPopover === columnKey(column)}
                                                    onPopoverVisibilityChange={(visible) => {
                                                        setOpenFilterPopover(null)
                                                        setOpenColumnPopover(visible ? columnKey(column) : null)
                                                    }}
                                                />
                                            ),
                                            dataIndex: alias,
                                            key: columnKey(column),
                                            width: MAX_COLUMN_WIDTH,
                                            className:
                                                'align-top whitespace-pre-wrap break-words max-w-[20rem] text-left',
                                            render: function RenderCell(value) {
                                                return <BIColumnValue value={value} />
                                            },
                                        }))}
                                    />
                                </div>
                                {hasMoreRows && (
                                    <div className="pt-2">
                                        <LemonButton
                                            type="secondary"
                                            fullWidth
                                            onClick={() => setLimit(limit + rows.length)}
                                            loading={queryResponseLoading}
                                        >
                                            Load {rows.length} more rows
                                        </LemonButton>
                                    </div>
                                )}
                            </div>
                        )}
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}

interface SchemaEditorViewProps {
    databaseName: string
    tables: DatabaseSchemaTable[]
    selectedTable: DatabaseSchemaTable | null
    draft: string
    versions: BISchemaVersion[]
    onClose: () => void
    onSelectTable: (tableName: string) => void
    onChangeDraft: (tableName: string, draft: string) => void
    onSave: (tableName: string, draft: string) => void
}

function SchemaEditorView({
    databaseName,
    tables,
    selectedTable,
    draft,
    versions,
    onClose,
    onSelectTable,
    onChangeDraft,
    onSave,
}: SchemaEditorViewProps): JSX.Element {
    const [historyOpen, setHistoryOpen] = useState(false)
    const activeTableName = selectedTable?.name || null
    const orderedVersions = [...versions]
    const lastSaved = orderedVersions[orderedVersions.length - 1] || null
    const generatedTemplate = selectedTable ? buildCreateTableStatement(selectedTable, databaseName) : ''
    const editorValue = draft || generatedTemplate

    const handleSave = (): void => {
        if (!activeTableName) {
            return
        }

        onSave(activeTableName, editorValue)
    }

    return (
        <div className="flex flex-col gap-3 h-full">
            <div className="flex gap-1 h-full min-h-0">
                <ResizableElement
                    defaultWidth={260}
                    minWidth={MIN_SIDEBAR_WIDTH}
                    maxWidth={400}
                    className="shrink-0 h-full min-h-0"
                >
                    <div className="h-full min-h-0 flex flex-col pr-2 gap-2">
                        <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                                <LemonButton type="tertiary" icon={<IconArrowLeft />} onClick={onClose} />
                                <div>
                                    <div className="text-muted text-xs">Modify database schema</div>
                                    <div className="font-semibold">{databaseName}</div>
                                </div>
                            </div>
                            {lastSaved && (
                                <div className="text-muted text-xs">
                                    Last saved {new Date(lastSaved.savedAt).toLocaleString()}
                                </div>
                            )}
                        </div>
                        <div className="flex-1 overflow-y-auto">
                            {tables.length === 0 ? (
                                <div className="text-muted text-sm">No tables available for this database.</div>
                            ) : (
                                tables.map((table) => (
                                    <LemonButton
                                        key={table.name}
                                        fullWidth
                                        className="justify-start"
                                        type={table.name === activeTableName ? 'primary' : 'tetriary'}
                                        onClick={() => onSelectTable(table.name)}
                                    >
                                        <div className="flex flex-col items-start">
                                            <span className="font-semibold">{table.name}</span>
                                            {table.schema_metadata?.engine && (
                                                <span className="text-muted text-xs">
                                                    {table.schema_metadata.engine}
                                                </span>
                                            )}
                                        </div>
                                    </LemonButton>
                                ))
                            )}
                        </div>
                    </div>
                </ResizableElement>

                <div className="flex-1 min-w-0 flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                        <LemonButton type="primary" onClick={handleSave} disabled={!activeTableName}>
                            Save
                        </LemonButton>
                        <Popover
                            visible={historyOpen}
                            onVisibilityChange={setHistoryOpen}
                            overlay={
                                <div className="p-2 space-y-2" onClick={(event) => event.stopPropagation()}>
                                    {orderedVersions.length === 0 && (
                                        <div className="text-muted text-sm">No saved versions yet.</div>
                                    )}
                                    {[...orderedVersions].reverse().map((version, index) => (
                                        <div
                                            key={`${version.savedAt}-${index}`}
                                            className="border border-border rounded p-2 space-y-1"
                                        >
                                            <div className="flex items-center justify-between text-xs text-muted">
                                                <span>Version {orderedVersions.length - index}</span>
                                                <span>{new Date(version.savedAt).toLocaleString()}</span>
                                            </div>
                                            <div className="text-xs text-muted whitespace-pre-wrap line-clamp-2">
                                                {version.sql}
                                            </div>
                                            {activeTableName && (
                                                <LemonButton
                                                    size="xsmall"
                                                    type="secondary"
                                                    onClick={() => {
                                                        onChangeDraft(activeTableName, version.sql)
                                                        setHistoryOpen(false)
                                                    }}
                                                >
                                                    Load version
                                                </LemonButton>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            }
                        >
                            <LemonButton
                                type="secondary"
                                icon={<IconClock />}
                                onClick={(event) => {
                                    event.stopPropagation()
                                    setHistoryOpen((current) => !current)
                                }}
                                disabled={!activeTableName}
                            >
                                Version history
                            </LemonButton>
                        </Popover>
                    </div>

                    <LemonCard className="flex-1 min-h-0 flex flex-col p-4" hoverEffect={false}>
                        <div className="flex items-center justify-between mb-2">
                            <div>
                                <div className="text-muted text-xs">Editing schema</div>
                                <div className="text-lg font-semibold">
                                    {selectedTable?.name || 'Select a table to edit its schema'}
                                </div>
                            </div>
                            <div className="text-xs text-muted">SQL definition</div>
                        </div>
                        <div className="flex-1 min-h-0 border border-border rounded bg-bg-3000">
                            {activeTableName ? (
                                <CodeEditor
                                    language="sql"
                                    value={editorValue}
                                    onChange={(value) => onChangeDraft(activeTableName, value || '')}
                                    height="100%"
                                    options={{
                                        minimap: { enabled: false },
                                        wordWrap: 'on',
                                        automaticLayout: true,
                                    }}
                                />
                            ) : (
                                <div className="p-3 text-muted">Select a table to begin editing its schema.</div>
                            )}
                        </div>
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}

function BIColumnValue({ value }: { value: unknown }): JSX.Element | string {
    const renderText = (text: string): JSX.Element => {
        const shouldClamp = text.length > MIN_CHARS_TO_CLAMP || text.includes('\n')

        return (
            <div className="break-words whitespace-pre-wrap">
                {shouldClamp ? <ClampedText lines={MAX_CELL_LINES} text={text} /> : text}
            </div>
        )
    }

    if (typeof value === 'number') {
        return humanFriendlyNumber(value)
    }

    if (value === null || value === undefined) {
        return '—'
    }

    if (typeof value === 'string') {
        const dayMatch = value.match(/^(\d{4}-\d{2}-\d{2})T00:00:00(?:\.000)?Z$/)

        if (dayMatch) {
            return dayMatch[1]
        }

        return renderText(value)
    }

    const stringValue = typeof value === 'object' ? JSON.stringify(value) || String(value) : String(value)

    return renderText(stringValue)
}

function ColumnHeader({
    column,
    field,
    alias,
    sortDirection,
    onRemove,
    onAddFilter,
    onSort,
    onSetAggregation,
    onSetTimeInterval,
    isPopoverOpen,
    onPopoverVisibilityChange,
}: {
    column: BIQueryColumn
    field?: DatabaseSchemaField
    alias: string
    sortDirection: BISortDirection | null
    onRemove: () => void
    onAddFilter: (expression?: string) => void
    onSort: (direction: BISortDirection | null) => void
    onSetAggregation: (aggregation?: BIAggregation | null) => void
    onSetTimeInterval: (timeInterval?: BITimeAggregation | null) => void
    isPopoverOpen: boolean
    onPopoverVisibilityChange: (visible: boolean) => void
}): JSX.Element {
    const [draft, setDraft] = useState('')
    const isTemporal = isTemporalField(field)
    const isNumeric = isNumericField(field)
    const availableAggregations: BIAggregation[] = isNumeric ? ['count', 'min', 'max', 'sum'] : ['count', 'min', 'max']

    return (
        <div className="flex items-center gap-1">
            <span
                className="font-semibold cursor-pointer"
                onClick={(event) => {
                    event.stopPropagation()
                    onRemove()
                }}
            >
                {alias}
            </span>
            <Popover
                visible={isPopoverOpen}
                onVisibilityChange={onPopoverVisibilityChange}
                overlay={
                    <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                        <LemonButton
                            status="danger"
                            size="small"
                            type="secondary"
                            onClick={() => {
                                onRemove()
                                onPopoverVisibilityChange(false)
                            }}
                        >
                            Remove column
                        </LemonButton>
                        <LemonInput
                            placeholder="= 'value' or > 10"
                            value={draft}
                            onChange={setDraft}
                            onPressEnter={() => {
                                onAddFilter(draft)
                                setDraft('')
                                onPopoverVisibilityChange(false)
                            }}
                        />
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                onAddFilter(draft)
                                setDraft('')
                                onPopoverVisibilityChange(false)
                            }}
                            icon={<IconFilter />}
                        >
                            Add filter
                        </LemonButton>
                        <div className="space-y-1">
                            <div className="text-muted">Aggregation</div>
                            <div className="grid grid-cols-4 gap-1">
                                <LemonButton
                                    type={!column.aggregation ? 'primary' : 'secondary'}
                                    size="small"
                                    active={!column.aggregation}
                                    status={!column.aggregation ? 'primary' : 'default'}
                                    onClick={() => {
                                        onSetAggregation(null)
                                        onPopoverVisibilityChange(false)
                                    }}
                                >
                                    None
                                </LemonButton>
                                {availableAggregations.map((aggregation) => (
                                    <LemonButton
                                        key={aggregation}
                                        type={column.aggregation === aggregation ? 'primary' : 'secondary'}
                                        size="small"
                                        status={column.aggregation === aggregation ? 'primary' : 'default'}
                                        active={column.aggregation === aggregation}
                                        onClick={() => {
                                            onSetAggregation(aggregation)
                                            onPopoverVisibilityChange(false)
                                        }}
                                    >
                                        {aggregation.toUpperCase()}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>
                        {isTemporal && (
                            <div className="space-y-1">
                                <div className="text-muted">Date aggregation</div>
                                <div className="grid grid-cols-4 gap-1">
                                    {[null, 'hour', 'day', 'week', 'month'].map((interval) => (
                                        <LemonButton
                                            key={interval || 'none'}
                                            type="secondary"
                                            size="small"
                                            status={column.timeInterval === interval ? 'primary' : 'default'}
                                            active={column.timeInterval === interval}
                                            onClick={() => {
                                                onSetTimeInterval(interval as BITimeAggregation | null)
                                                onPopoverVisibilityChange(false)
                                            }}
                                        >
                                            {(interval || 'none').toString().replace(/^./, (c) => c.toUpperCase())}
                                        </LemonButton>
                                    ))}
                                </div>
                            </div>
                        )}
                        <div className="grid grid-cols-2 gap-1">
                            {(['asc', 'desc'] as BISortDirection[]).map((direction) => (
                                <LemonButton
                                    key={direction}
                                    type="secondary"
                                    size="small"
                                    status={sortDirection === direction ? 'primary' : 'default'}
                                    active={sortDirection === direction}
                                    onClick={() => {
                                        onSort(sortDirection === direction ? null : direction)
                                        onPopoverVisibilityChange(false)
                                    }}
                                >
                                    Sort {direction}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconFilter />}
                    aria-label="Column options"
                    onClick={(event) => {
                        event.stopPropagation()
                        onPopoverVisibilityChange(!isPopoverOpen)
                    }}
                />
            </Popover>
        </div>
    )
}

function isNumericField(field?: DatabaseSchemaField): boolean {
    if (!field?.type || typeof field.type !== 'string') {
        return false
    }
    const type = field.type.toLowerCase()
    return type.includes('int') || type.includes('float') || type.includes('decimal') || type.includes('double')
}

function isTemporalField(field?: DatabaseSchemaField): boolean {
    if (!field?.type || typeof field.type !== 'string') {
        return false
    }
    const type = field.type.toLowerCase()
    return type.includes('date') || type.includes('time')
}

function FilterPill({
    filter,
    isOpen,
    onOpenChange,
    onUpdate,
    onRemove,
}: {
    filter: BIQueryFilter
    isOpen: boolean
    onOpenChange: (visible: boolean) => void
    onUpdate: (expression: string) => void
    onRemove: () => void
}): JSX.Element {
    const [draft, setDraft] = useState(filter.expression)

    useEffect(() => {
        setDraft(filter.expression)
    }, [filter.expression])

    return (
        <Popover
            visible={isOpen}
            onVisibilityChange={onOpenChange}
            overlay={
                <div className="space-y-2" onClick={(event) => event.stopPropagation()}>
                    <LemonInput
                        placeholder="= 'value' or > 10"
                        value={draft}
                        onChange={setDraft}
                        onPressEnter={() => {
                            onUpdate(draft)
                            onOpenChange(false)
                        }}
                    />
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                onUpdate(draft)
                                onOpenChange(false)
                            }}
                        >
                            Update filter
                        </LemonButton>
                        <LemonButton
                            status="danger"
                            onClick={() => {
                                onRemove()
                                onOpenChange(false)
                            }}
                        >
                            Remove
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div
                className="cursor-pointer"
                onClick={(event) => {
                    event.stopPropagation()
                    onOpenChange(!isOpen)
                }}
            >
                {formatFilter(filter)}
            </div>
        </Popover>
    )
}

function fieldTypeIcon(field?: DatabaseSchemaField): JSX.Element {
    if (!field?.type || typeof field.type !== 'string') {
        return <IconQuestion />
    }

    const type = field.type.toLowerCase()

    if (isNumericField(field) || type.includes('decimal') || type.includes('number')) {
        return <IconCalculator />
    }

    if (type.includes('date') || type.includes('time')) {
        return <IconCalendar />
    }

    if (type.includes('bool')) {
        return <IconBinary />
    }

    if (type.includes('array')) {
        return <IconList />
    }

    if (isJsonField(field)) {
        return <IconBrackets />
    }

    return <IconLetter />
}
