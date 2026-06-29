import clsx from 'clsx'
import {
    KeyboardEvent,
    MouseEvent as ReactMouseEvent,
    PointerEvent as ReactPointerEvent,
    ReactNode,
    memo,
    useMemo,
    useRef,
    useState,
} from 'react'

import { IconDatabase, IconEye, IconGraph, IconHide, IconList, IconPencil, IconPeople, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { PostHogErrorBoundary } from '@posthog/react'

import { ComponentPanelContext } from './componentPanelContext'
import {
    ComponentPanel,
    ComponentPanelVisibility,
    DEFAULT_COMPONENT_PANEL_VISIBILITY,
    withPersistedComponentPanelProps,
} from './componentPanels'
import { getNotebookObjectProp, getNotebookStringProp } from './documentModel'
import { InsertMenuSelectionDirection } from './editorTypes'
import { getMarkdownNotebookComponentDefinition } from './registry'
import {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookComponentDefinition,
    NotebookComponentProps,
    NotebookComponentRegistry,
    NotebookMode,
} from './types'
import { getNodeFingerprint } from './utils'

export type ComponentTitleTone = 'default' | 'insight' | 'sql' | 'data' | 'media' | 'experiment' | 'code' | 'posthog'

export type ComponentTitleDisplay = {
    label: string
    tone: ComponentTitleTone
    icon: ReactNode
}

export type NotebookComponentShellProps = {
    node: NotebookComponentBlockNode
    mode: NotebookMode
    componentPanels: ComponentPanelVisibility
    rememberedComponentPanels?: ComponentPanelVisibility
    persistComponentPanelVisibility: boolean
    isSelected: boolean
    registry: NotebookComponentRegistry
    toggleComponentPanel: (panel: ComponentPanel) => void
    setLocalComponentPanels: (nodeId: string, panels: ComponentPanelVisibility) => void
    rememberComponentPanels: (nodeId: string, panels: ComponentPanelVisibility) => void
    setBlockRef: (element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    deleteNode: () => void
    deleteSelectedNotebookBlocks: () => boolean
    insertParagraphAfterNode: () => void
    moveFocusToAdjacentNode: (nodeId: string, direction: InsertMenuSelectionDirection, offset: number) => boolean
}

export function NotebookComponentShell({
    node,
    mode,
    componentPanels,
    rememberedComponentPanels,
    persistComponentPanelVisibility,
    isSelected,
    registry,
    toggleComponentPanel,
    setLocalComponentPanels,
    rememberComponentPanels,
    setBlockRef,
    updateNode,
    deleteNode,
    deleteSelectedNotebookBlocks,
    insertParagraphAfterNode,
    moveFocusToAdjacentNode,
}: NotebookComponentShellProps): JSX.Element {
    const definition = getMarkdownNotebookComponentDefinition(registry, node.tagName)
    const errors = [...(node.errors ?? []), ...(definition?.validateProps?.(node.props) ?? [])]
    const ViewComponent = definition?.ViewComponent
    const EditComponent = definition?.EditComponent ?? definition?.ViewComponent
    const showEditPanel = mode === 'edit' && componentPanels.filters
    const showViewPanel =
        (mode === 'view' || componentPanels.results) && !(showEditPanel && definition?.exclusiveEditPanel)
    const showModeActions = mode === 'edit' && !!definition && !definition.hideModeActions
    const canToggleComponentPanels = mode === 'edit'
    const hasOpenComponentPanel = componentPanels.filters || componentPanels.results
    const titleDisplay = getComponentTitleDisplay(node, definition)
    const toolbarTitle = getComponentToolbarTitle(node, definition, titleDisplay.label)
    // The user-set title (props.title) wins; the computed contextual title is the watermark/fallback.
    // A title equal to the component's own label (e.g. code blocks default to "Python") is treated
    // as "no user title" so the field reads as empty by default.
    const rawTitle = (getNotebookStringProp(node.props.title) ?? '').trim()
    const userTitle = rawTitle && rawTitle !== titleDisplay.label ? rawTitle : ''
    const titlePlaceholder = toolbarTitle ?? 'Add a title'
    const resolvedTitle = userTitle || toolbarTitle || null
    const filtersLabel = componentPanels.filters ? 'Hide filters' : 'Show filters'
    const resultsLabel = componentPanels.results ? 'Hide results' : 'Show results'
    const titleClassName = clsx(
        'MarkdownNotebook__component-title',
        `MarkdownNotebook__component-title--${titleDisplay.tone}`
    )
    const componentPanelState = useMemo(
        () => ({
            componentPanels,
            showEditPanel,
            showViewPanel,
        }),
        [componentPanels, showEditPanel, showViewPanel]
    )
    const [titleDraft, setTitleDraft] = useState<string | null>(null)
    // Escape blurs the input, which fires commitTitle synchronously before the titleDraft
    // state update lands — this ref lets commitTitle see the cancel intent in that same tick
    const cancellingTitleRef = useRef(false)
    const titleInputValue = titleDraft ?? userTitle
    const titleContent = (
        <>
            {titleDisplay.icon ? (
                <span className="MarkdownNotebook__component-title-icon">{titleDisplay.icon}</span>
            ) : null}
            <span>{titleDisplay.label}</span>
        </>
    )
    const setComponentPanels = (panels: ComponentPanelVisibility): void => {
        if (!persistComponentPanelVisibility) {
            setLocalComponentPanels(node.id, panels)
            return
        }

        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'component') {
                return currentNode
            }

            const currentDefinition = getMarkdownNotebookComponentDefinition(registry, currentNode.tagName)
            return withPersistedComponentPanelProps(currentNode, currentDefinition, panels)
        })
    }
    const toggleAllComponentPanels = (): void => {
        const restoredPanelVisibility =
            rememberedComponentPanels && (rememberedComponentPanels.filters || rememberedComponentPanels.results)
                ? rememberedComponentPanels
                : DEFAULT_COMPONENT_PANEL_VISIBILITY
        const nextPanelVisibility = hasOpenComponentPanel ? { filters: false, results: false } : restoredPanelVisibility

        if (hasOpenComponentPanel) {
            rememberComponentPanels(node.id, componentPanels)
        }

        setComponentPanels(nextPanelVisibility)
    }
    const updateProps = (props: Partial<NotebookComponentProps>): void => {
        const propKeysToRemove = new Set(
            Object.entries(props)
                .filter(([, value]) => value === undefined)
                .map(([key]) => key)
        )
        const nextProps = Object.entries(props).reduce<NotebookComponentProps>((accumulator, [key, value]) => {
            if (value !== undefined) {
                accumulator[key] = value
            }
            return accumulator
        }, {})

        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'component') {
                return currentNode
            }
            return {
                ...currentNode,
                // An intentional edit supersedes any malformed source captured at parse time —
                // stale `raw` would otherwise win over the new props on serialize
                raw: undefined,
                errors: undefined,
                props: {
                    ...Object.entries(currentNode.props).reduce<NotebookComponentProps>((accumulator, [key, value]) => {
                        if (!propKeysToRemove.has(key)) {
                            accumulator[key] = value
                        }
                        return accumulator
                    }, {}),
                    ...nextProps,
                },
            }
        })
    }
    const commitTitle = (): void => {
        if (cancellingTitleRef.current) {
            cancellingTitleRef.current = false
            return
        }
        if (titleDraft === null) {
            return
        }
        const nextTitle = titleDraft.trim()
        setTitleDraft(null)
        if (nextTitle !== userTitle) {
            updateProps({ title: nextTitle || undefined })
        }
    }
    const handleTitleKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
        if (event.key === 'Enter') {
            event.preventDefault()
            event.currentTarget.blur()
        } else if (event.key === 'Escape') {
            event.preventDefault()
            cancellingTitleRef.current = true
            setTitleDraft(null)
            event.currentTarget.blur()
        }
    }
    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
        if (mode !== 'edit' || event.target !== event.currentTarget) {
            return
        }

        if (event.key === 'Backspace' || event.key === 'Delete') {
            event.preventDefault()
            if (deleteSelectedNotebookBlocks()) {
                return
            }
        }

        if (event.key === 'Backspace') {
            deleteNode()
            return
        }

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (moveFocusToAdjacentNode(node.id, event.key === 'ArrowDown' ? 'next' : 'previous', 0)) {
                event.preventDefault()
                return
            }
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            insertParagraphAfterNode()
        }
    }
    const handleToolbarPointerDownCapture = (event: ReactPointerEvent<HTMLDivElement>): void => {
        if (event.button !== 0 || isTitleInputTarget(event.target)) {
            return
        }

        event.stopPropagation()
    }
    const handleToolbarMouseDownCapture = (event: ReactMouseEvent<HTMLDivElement>): void => {
        if (event.button !== 0 || isTitleInputTarget(event.target)) {
            return
        }

        event.preventDefault()
        event.stopPropagation()
    }

    return (
        <div
            className={clsx(
                'MarkdownNotebook__component-shell',
                isSelected && 'MarkdownNotebook__component-shell--selected',
                errors.length && 'MarkdownNotebook__component-shell--error'
            )}
            ref={setBlockRef}
            contentEditable={false}
            tabIndex={mode === 'edit' ? 0 : undefined}
            onKeyDown={handleKeyDown}
        >
            <div
                className="MarkdownNotebook__component-toolbar"
                onPointerDownCapture={handleToolbarPointerDownCapture}
                onMouseDownCapture={handleToolbarMouseDownCapture}
            >
                <div className="MarkdownNotebook__component-toolbar-left">
                    {canToggleComponentPanels ? (
                        <button
                            type="button"
                            className={titleClassName}
                            aria-expanded={hasOpenComponentPanel}
                            onClick={toggleAllComponentPanels}
                        >
                            {titleContent}
                        </button>
                    ) : (
                        <div className={titleClassName}>{titleContent}</div>
                    )}
                    {showModeActions ? (
                        <div className="MarkdownNotebook__component-mode-actions">
                            <LemonButton
                                aria-label={filtersLabel}
                                size="xsmall"
                                icon={<IconPencil />}
                                active={componentPanels.filters}
                                tooltip={filtersLabel}
                                onClick={() => toggleComponentPanel('filters')}
                            />
                            <LemonButton
                                aria-label={resultsLabel}
                                size="xsmall"
                                icon={componentPanels.results ? <IconEye /> : <IconHide />}
                                active={componentPanels.results}
                                tooltip={resultsLabel}
                                onClick={() => toggleComponentPanel('results')}
                            />
                        </div>
                    ) : null}
                </div>
                {mode === 'edit' ? (
                    <input
                        className="MarkdownNotebook__component-toolbar-title MarkdownNotebook__component-toolbar-title--input"
                        value={titleInputValue}
                        placeholder={titlePlaceholder}
                        aria-label="Component title"
                        spellCheck={false}
                        onChange={(event) => setTitleDraft(event.target.value)}
                        onBlur={commitTitle}
                        onKeyDown={handleTitleKeyDown}
                    />
                ) : resolvedTitle ? (
                    <div className="MarkdownNotebook__component-toolbar-title" title={resolvedTitle}>
                        {resolvedTitle}
                    </div>
                ) : null}
                {mode === 'edit' ? (
                    <div className="MarkdownNotebook__component-actions">
                        <LemonButton
                            aria-label="Delete component"
                            size="xsmall"
                            icon={<IconTrash />}
                            tooltip="Delete"
                            status="danger"
                            onClick={deleteNode}
                        />
                    </div>
                ) : null}
            </div>
            <ComponentPanelContext.Provider value={componentPanelState}>
                {errors.length ? (
                    <div className="MarkdownNotebook__component-errors">
                        {errors.map((error) => (
                            <div key={error}>{error}</div>
                        ))}
                    </div>
                ) : null}
                {showEditPanel && EditComponent ? (
                    <div className="MarkdownNotebook__component-panel">
                        <NotebookComponentPanelErrorBoundary node={node} panel="filters">
                            <EditComponent
                                node={node}
                                mode="edit"
                                notebookMode={mode}
                                updateProps={updateProps}
                                deleteNode={deleteNode}
                            />
                        </NotebookComponentPanelErrorBoundary>
                    </div>
                ) : null}
                {showViewPanel ? (
                    <div className="MarkdownNotebook__component-panel">
                        {ViewComponent ? (
                            <NotebookComponentPanelErrorBoundary node={node} panel="results">
                                <ViewComponent
                                    node={node}
                                    mode="view"
                                    notebookMode={mode}
                                    updateProps={updateProps}
                                    deleteNode={deleteNode}
                                />
                            </NotebookComponentPanelErrorBoundary>
                        ) : (
                            <UnknownComponentView node={node} />
                        )}
                    </div>
                ) : null}
            </ComponentPanelContext.Provider>
        </div>
    )
}

function isTitleInputTarget(target: EventTarget | null): boolean {
    return target instanceof HTMLElement && !!target.closest('.MarkdownNotebook__component-toolbar-title--input')
}

export function NotebookComponentPanelErrorBoundary({
    children,
    node,
    panel,
}: {
    children: ReactNode
    node: NotebookComponentBlockNode
    panel: ComponentPanel
}): JSX.Element {
    return (
        <PostHogErrorBoundary
            key={`${node.id}-${panel}`}
            additionalProperties={{
                feature: 'markdown_notebook_component',
                markdown_notebook_node_id: node.id,
                markdown_notebook_tag_name: node.tagName,
                markdown_notebook_panel: panel,
            }}
            fallback={({ error }) => <NotebookComponentRenderError error={error} node={node} panel={panel} />}
        >
            {children}
        </PostHogErrorBoundary>
    )
}

export function NotebookComponentRenderError({
    error,
    node,
    panel,
}: {
    error: unknown
    node: NotebookComponentBlockNode
    panel: ComponentPanel
}): JSX.Element {
    const message =
        error instanceof Error && error.message
            ? error.message
            : typeof error === 'string' && error
              ? error
              : 'Unknown error'

    return (
        <div className="MarkdownNotebook__component-preview MarkdownNotebook__component-render-error">
            <strong>This block couldn't render.</strong>
            <span className="text-secondary text-sm">
                The <code>{`<${node.tagName} />`}</code> {panel === 'filters' ? 'filters' : 'results'} panel crashed.
            </span>
            <code>{message}</code>
        </div>
    )
}

export function UnknownComponentView({ node }: { node: NotebookComponentBlockNode }): JSX.Element {
    const [arePropsVisible, setArePropsVisible] = useState(false)

    return (
        <div className="MarkdownNotebook__unknown-component">
            <div className="MarkdownNotebook__unknown-component-header">
                <div className="MarkdownNotebook__unknown-component-message">
                    <strong>This tag is unknown.</strong>
                    <span>
                        The <code>{`<${node.tagName} />`}</code> tag is not registered as a markdown notebook component.
                    </span>
                </div>
                <LemonButton
                    size="xsmall"
                    icon={arePropsVisible ? <IconHide /> : <IconEye />}
                    onClick={() => setArePropsVisible(!arePropsVisible)}
                >
                    {arePropsVisible ? 'Hide props' : 'Show props'}
                </LemonButton>
            </div>
            {arePropsVisible ? <pre>{JSON.stringify(node.props, null, 2)}</pre> : null}
        </div>
    )
}

export const MemoizedNotebookComponentShell = memo(NotebookComponentShell, areNotebookComponentShellPropsEqual)

export function areNotebookComponentShellPropsEqual(
    previousProps: NotebookComponentShellProps,
    nextProps: NotebookComponentShellProps
): boolean {
    const previousDefinition = getMarkdownNotebookComponentDefinition(
        previousProps.registry,
        previousProps.node.tagName
    )
    const nextDefinition = getMarkdownNotebookComponentDefinition(nextProps.registry, nextProps.node.tagName)

    return (
        previousProps.mode === nextProps.mode &&
        previousProps.updateNode === nextProps.updateNode &&
        previousProps.deleteSelectedNotebookBlocks === nextProps.deleteSelectedNotebookBlocks &&
        previousProps.moveFocusToAdjacentNode === nextProps.moveFocusToAdjacentNode &&
        previousDefinition === nextDefinition &&
        previousProps.node.id === nextProps.node.id &&
        previousProps.isSelected === nextProps.isSelected &&
        previousProps.persistComponentPanelVisibility === nextProps.persistComponentPanelVisibility &&
        previousProps.componentPanels.filters === nextProps.componentPanels.filters &&
        previousProps.componentPanels.results === nextProps.componentPanels.results &&
        previousProps.rememberedComponentPanels?.filters === nextProps.rememberedComponentPanels?.filters &&
        previousProps.rememberedComponentPanels?.results === nextProps.rememberedComponentPanels?.results &&
        (previousProps.node === nextProps.node ||
            getNodeFingerprint(previousProps.node) === getNodeFingerprint(nextProps.node))
    )
}

export function getComponentTitleDisplay(
    node: NotebookComponentBlockNode,
    definition: NotebookComponentDefinition | null
): ComponentTitleDisplay {
    if (node.tagName === 'Query') {
        return getQueryComponentTitleDisplay(node, definition)
    }

    const label = definition?.label ?? node.tagName
    const tone = getComponentTitleTone(node.tagName, definition?.category)

    return {
        label,
        tone,
        icon: definition?.icon ?? getComponentTitleFallbackIcon(tone),
    }
}

export function getComponentToolbarTitle(
    node: NotebookComponentBlockNode,
    definition: NotebookComponentDefinition | null,
    label: string
): string | null {
    if (
        node.tagName === 'Query' &&
        getNotebookStringProp(getNotebookObjectProp(node.props.query)?.kind) === 'SavedInsightNode'
    ) {
        return null
    }
    const title = definition?.getTitle?.(node) ?? getNotebookStringProp(node.props.title)
    const trimmedTitle = title?.trim()
    return trimmedTitle && trimmedTitle !== label ? trimmedTitle : null
}

export function getQueryComponentTitleDisplay(
    node: NotebookComponentBlockNode,
    definition: NotebookComponentDefinition | null
): ComponentTitleDisplay {
    const query = getNotebookObjectProp(node.props.query)
    const source = getNotebookObjectProp(query?.source)
    const queryKind = getNotebookStringProp(query?.kind)
    const sourceKind = getNotebookStringProp(source?.kind)

    if (sourceKind === 'HogQLQuery') {
        return { label: 'SQL', tone: 'sql', icon: <IconDatabase /> }
    }
    if (sourceKind === 'FunnelsQuery') {
        return { label: 'Funnel', tone: 'insight', icon: <IconGraph /> }
    }
    if (sourceKind === 'TrendsQuery') {
        return { label: 'Trend', tone: 'insight', icon: <IconGraph /> }
    }
    if (queryKind === 'SavedInsightNode') {
        return { label: 'Saved insight', tone: 'insight', icon: <IconGraph /> }
    }
    if (sourceKind === 'EventsQuery') {
        return { label: 'Events', tone: 'data', icon: <IconList /> }
    }
    if (sourceKind === 'ActorsQuery') {
        return { label: 'People', tone: 'data', icon: <IconPeople /> }
    }

    return {
        label: definition?.label ?? node.tagName,
        tone: 'insight',
        icon: definition?.icon ?? <IconGraph />,
    }
}

export function getComponentTitleTone(tagName: string, category: string | undefined): ComponentTitleTone {
    if (tagName === 'Experiment') {
        return 'experiment'
    }

    if (tagName === 'DuckSQL' || tagName === 'HogQLSQL') {
        return 'sql'
    }

    if (category === 'Insight') {
        return 'insight'
    }
    if (category === 'Code') {
        return 'code'
    }
    if (category === 'Data') {
        return 'data'
    }
    if (category === 'Media') {
        return 'media'
    }
    if (category === 'PostHog') {
        return 'posthog'
    }
    return 'default'
}

export function getComponentTitleFallbackIcon(tone: ComponentTitleTone): ReactNode {
    if (tone === 'sql') {
        return <IconDatabase />
    }
    if (tone === 'insight' || tone === 'experiment') {
        return <IconGraph />
    }
    if (tone === 'data' || tone === 'media') {
        return <IconList />
    }
    return null
}
