import '../Nodes/NotebookNodeBacklink'
import '../Nodes/NotebookNodeCohort'
import '../Nodes/NotebookNodeCustomerJourney/NotebookNodeCustomerJourney'
import '../Nodes/NotebookNodeDuckSQL'
import '../Nodes/NotebookNodeEarlyAccessFeature'
import '../Nodes/NotebookNodeEmbed'
import '../Nodes/NotebookNodeExperiment'
import '../Nodes/NotebookNodeFlag'
import '../Nodes/NotebookNodeFlagCodeExample'
import '../Nodes/NotebookNodeGroup'
import '../Nodes/NotebookNodeGroupProperties'
import '../Nodes/NotebookNodeHogQL'
import '../Nodes/NotebookNodeImage'
import '../Nodes/NotebookNodeIssues'
import '../Nodes/NotebookNodeLatex'
import '../Nodes/NotebookNodeLLMTrace'
import '../Nodes/NotebookNodeMap'
import '../Nodes/NotebookNodePerson'
import '../Nodes/NotebookNodePersonFeed/NotebookNodePersonFeed'
import '../Nodes/NotebookNodePersonProperties'
import '../Nodes/NotebookNodePlaylist'
import '../Nodes/NotebookNodePython'
import '../Nodes/NotebookNodeQuery'
import '../Nodes/NotebookNodeRecording'
import '../Nodes/NotebookNodeRelatedGroups'
import '../Nodes/NotebookNodeReplayTimestamp'
import '../Nodes/NotebookNodeSupportTickets'
import '../Nodes/NotebookNodeSurvey'
import '../Nodes/NotebookNodeTaskCreate'
import '../Nodes/NotebookNodeUsageMetrics'
import '../Nodes/NotebookNodeZendeskTickets'

import clsx from 'clsx'
import { BindLogic, useActions, useMountedLogic } from 'kea'
import {
    type CSSProperties,
    type PointerEvent as ReactPointerEvent,
    useCallback,
    useEffect,
    useMemo,
    useRef,
} from 'react'

import { IconComment, IconSparkles } from '@posthog/icons'
import { LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { createMarkdownNotebookRegistry } from 'lib/components/MarkdownNotebook'
import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { isDiscussionCommentProps } from 'lib/components/MarkdownNotebook/markdown'
import {
    NotebookComponentBlockNode,
    NotebookComponentDefinition,
    NotebookComponentProps,
    NotebookComponentRenderProps,
    NotebookComponentRegistry,
    NotebookPropValue,
} from 'lib/components/MarkdownNotebook/types'
import { isNotebookPropValue } from 'lib/components/MarkdownNotebook/utils'

import { NODE_ICONS } from '../nodeIcons'
import { NotebookNodeContext } from '../Nodes/NotebookNodeContext'
import { notebookNodeLogic } from '../Nodes/notebookNodeLogic'
import { CreatePostHogWidgetNodeOptions, NotebookNodeAttributes, NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import { NotebookAIChat, getNotebookAIChatTitle } from './MarkdownNotebookAIChat'
import { NotebookDiscussionComment, getNotebookDiscussionCommentTitle } from './MarkdownNotebookDiscussionComment'
import { notebookLogic } from './notebookLogic'

export const MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE: Partial<Record<string, NotebookNodeType>> = {
    Query: NotebookNodeType.Query,
    Python: NotebookNodeType.Python,
    DuckSQL: NotebookNodeType.DuckSQL,
    HogQLSQL: NotebookNodeType.HogQLSQL,
    Recording: NotebookNodeType.Recording,
    RecordingPlaylist: NotebookNodeType.RecordingPlaylist,
    FeatureFlag: NotebookNodeType.FeatureFlag,
    FeatureFlagCodeExample: NotebookNodeType.FeatureFlagCodeExample,
    Experiment: NotebookNodeType.Experiment,
    EarlyAccessFeature: NotebookNodeType.EarlyAccessFeature,
    Survey: NotebookNodeType.Survey,
    Person: NotebookNodeType.Person,
    Group: NotebookNodeType.Group,
    Cohort: NotebookNodeType.Cohort,
    Backlink: NotebookNodeType.Backlink,
    ReplayTimestamp: NotebookNodeType.ReplayTimestamp,
    Image: NotebookNodeType.Image,
    PersonFeed: NotebookNodeType.PersonFeed,
    PersonProperties: NotebookNodeType.PersonProperties,
    GroupProperties: NotebookNodeType.GroupProperties,
    Map: NotebookNodeType.Map,
    Embed: NotebookNodeType.Embed,
    Latex: NotebookNodeType.Latex,
    TaskCreate: NotebookNodeType.TaskCreate,
    LLMTrace: NotebookNodeType.LLMTrace,
    Issues: NotebookNodeType.Issues,
    UsageMetrics: NotebookNodeType.UsageMetrics,
    ZendeskTickets: NotebookNodeType.ZendeskTickets,
    RelatedGroups: NotebookNodeType.RelatedGroups,
    CustomerJourney: NotebookNodeType.CustomerJourney,
    SupportTickets: NotebookNodeType.SupportTickets,
}

export const MARKDOWN_NODE_DEFINITIONS: {
    tagName: string
    category: string
    label?: string
    EditComponent?: NotebookComponentDefinition['EditComponent']
    exclusiveEditPanel?: boolean
    insertCommand?: NotebookComponentDefinition['insertCommand']
}[] = [
    { tagName: 'Query', category: 'Insight' },
    { tagName: 'Python', category: 'Code', exclusiveEditPanel: true },
    { tagName: 'DuckSQL', category: 'SQL', label: 'SQL (DuckDB)' },
    { tagName: 'HogQLSQL', category: 'SQL', label: 'SQL (HogQL)' },
    { tagName: 'RecordingPlaylist', category: 'Data', label: 'Session recordings', exclusiveEditPanel: true },
    { tagName: 'Experiment', category: 'Experiment', exclusiveEditPanel: true },
    { tagName: 'Image', category: 'Media', EditComponent: ImageEdit },
    { tagName: 'Embed', category: 'Media', EditComponent: EmbedEdit },
    { tagName: 'Latex', category: 'Media', label: 'LaTeX', EditComponent: LatexEdit },
    { tagName: 'FeatureFlag', category: 'PostHog', label: 'Feature flag', exclusiveEditPanel: true },
    { tagName: 'Survey', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'Person', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'Group', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'Cohort', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'Map', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'Recording', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'Backlink', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'ReplayTimestamp', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'PersonFeed', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'PersonProperties', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'GroupProperties', category: 'Data', exclusiveEditPanel: true },
    { tagName: 'TaskCreate', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'LLMTrace', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'Issues', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'UsageMetrics', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'ZendeskTickets', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'RelatedGroups', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'CustomerJourney', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'SupportTickets', category: 'PostHog', exclusiveEditPanel: true },
    { tagName: 'EarlyAccessFeature', category: 'PostHog', label: 'Early access feature', exclusiveEditPanel: true },
    {
        tagName: 'FeatureFlagCodeExample',
        category: 'PostHog',
        label: 'Feature flag code example',
        exclusiveEditPanel: true,
    },
]

export const NOTEBOOK_MARKDOWN_REGISTRY: NotebookComponentRegistry = createMarkdownNotebookRegistry([
    ...MARKDOWN_NODE_DEFINITIONS.map((definition) => {
        const nodeType = MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[definition.tagName]
        const options = nodeType ? KNOWN_NODES[nodeType] : null
        const label = definition.label ?? options?.titlePlaceholder ?? splitTagName(definition.tagName)

        return {
            tagName: definition.tagName,
            label,
            category: definition.category,
            icon: nodeType ? NODE_ICONS[nodeType] : undefined,
            defaultProps: () => getDefaultPropsForNodeType(nodeType),
            ViewComponent: RealNotebookNodeView,
            EditComponent: definition.EditComponent ?? RealNotebookNodeEdit,
            exclusiveEditPanel: definition.exclusiveEditPanel,
            insertCommand: definition.insertCommand,
            getTitle: (node: NotebookComponentBlockNode) =>
                getMarkdownNotebookNodeTitle(node, nodeType, options, label),
        }
    }),
    {
        tagName: 'Chat',
        label: 'AI chat',
        category: 'AI',
        icon: <IconSparkles />,
        defaultProps: { id: '' },
        ViewComponent: NotebookAIChat,
        EditComponent: NotebookAIChat,
        exclusiveEditPanel: true,
        hideModeActions: true,
        getTitle: getNotebookAIChatTitle,
    },
    {
        // Overrides the default registry's authorial-note definition: the note flavor
        // (`text`, stored as `<!-- … -->`) renders through CommentBlock before the registry
        // is consulted, so this ViewComponent only ever sees the discussion flavor
        // (`ref` + `replies`, Google Docs-style threads anchored to a highlight).
        tagName: 'Comment',
        label: 'Comment',
        category: 'Text',
        description: 'Inline note, stored as a markdown comment',
        aliases: ['note', 'annotation', 'todo'],
        icon: <IconComment />,
        defaultProps: { text: '' },
        ViewComponent: NotebookDiscussionComment,
        EditComponent: NotebookDiscussionComment,
        exclusiveEditPanel: true,
        hideModeActions: true,
        insertCommand: {},
        getTitle: (node: NotebookComponentBlockNode) =>
            isDiscussionCommentProps(node.props)
                ? getNotebookDiscussionCommentTitle(node)
                : (getUnknownStringProp(node.props.text) ?? 'Comment'),
    },
])

export function getMarkdownNotebookNodeTitle(
    node: NotebookComponentBlockNode,
    nodeType: NotebookNodeType | undefined,
    options: CreatePostHogWidgetNodeOptions<any> | null,
    fallback: string
): string | null {
    const attributes = getNodeAttributes(node.props, node.id, options, nodeType, false)
    const explicitTitle = getUnknownStringProp(attributes.title)

    if (explicitTitle) {
        return explicitTitle
    }

    if (nodeType === NotebookNodeType.Query) {
        return getQueryTitle(attributes.query) ?? fallback
    }
    if (nodeType === NotebookNodeType.Embed) {
        return getUnknownStringProp(attributes.src) ?? fallback
    }
    if (nodeType === NotebookNodeType.Image) {
        return (
            getUnknownStringProp(attributes.alt) ??
            getUnknownStringProp((attributes.file as { name?: unknown } | undefined)?.name) ??
            getUnknownStringProp(attributes.src) ??
            fallback
        )
    }
    if (
        nodeType === NotebookNodeType.Python ||
        nodeType === NotebookNodeType.DuckSQL ||
        nodeType === NotebookNodeType.HogQLSQL
    ) {
        return summarizeTitle(getUnknownStringProp(attributes.code)) ?? fallback
    }

    return (
        summarizeTitle(options?.serializedText?.(attributes)) ??
        getUnknownStringProp(attributes.name) ??
        getUnknownStringProp(attributes.id) ??
        fallback
    )
}

export function getNotebookStringProp(value: NotebookPropValue | undefined): string | null {
    return typeof value === 'string' ? value : null
}

export function getNotebookObjectProp(value: NotebookPropValue | undefined): Record<string, NotebookPropValue> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

export function getUnknownStringProp(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function getQueryTitle(queryValue: unknown): string | null {
    if (!queryValue || typeof queryValue !== 'object' || Array.isArray(queryValue)) {
        return null
    }

    const query = queryValue as Record<string, NotebookPropValue>
    const source = getNotebookObjectProp(query.source)
    const queryKind = getNotebookStringProp(query.kind)
    const sourceKind = getNotebookStringProp(source?.kind)

    if (queryKind === 'SavedInsightNode') {
        return getNotebookStringProp(query.name) ?? getNotebookStringProp(query.shortId) ?? 'Saved insight'
    }
    if (sourceKind === 'HogQLQuery') {
        return summarizeTitle(getNotebookStringProp(source?.query)) ?? 'SQL query'
    }
    if (sourceKind === 'TrendsQuery') {
        return source ? (getSeriesTitle(source) ?? 'Trend') : 'Trend'
    }
    if (sourceKind === 'FunnelsQuery') {
        return 'Funnel'
    }
    if (sourceKind === 'EventsQuery') {
        return 'Events'
    }

    return queryKind ?? sourceKind
}

export function getSeriesTitle(query: Record<string, NotebookPropValue>): string | null {
    const series = query.series
    if (!Array.isArray(series)) {
        return null
    }

    const events = series
        .map((seriesItem) => {
            const seriesObject = getNotebookObjectProp(seriesItem)
            return getNotebookStringProp(seriesObject?.event)
        })
        .filter(Boolean)

    return events.length ? events.join(', ') : null
}

export function summarizeTitle(value: string | null | undefined): string | null {
    const oneLineValue = value?.replace(/\s+/g, ' ').trim()
    if (!oneLineValue) {
        return null
    }
    return oneLineValue.length > 120 ? `${oneLineValue.slice(0, 117)}...` : oneLineValue
}

export function RealNotebookNodeView(props: NotebookComponentRenderProps): JSX.Element {
    return <RealNotebookNodeComponent {...props} />
}

export function RealNotebookNodeEdit(props: NotebookComponentRenderProps): JSX.Element {
    return <RealNotebookNodeComponent {...props} forceEditing editOnly />
}

export function RealNotebookNodeComponent({
    node,
    mode,
    updateProps,
    deleteNode,
    forceEditing = false,
    editOnly = false,
}: NotebookComponentRenderProps & { forceEditing?: boolean; editOnly?: boolean }): JSX.Element {
    const notebookNodeType = MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[node.tagName]
    const options = notebookNodeType ? KNOWN_NODES[notebookNodeType] : null

    if (!options || !notebookNodeType) {
        return <div className="MarkdownNotebook__component-preview">Unsupported notebook node.</div>
    }

    return (
        <MountedRealNotebookNodeComponent
            node={node}
            mode={mode}
            updateProps={updateProps}
            deleteNode={deleteNode}
            editOnly={editOnly}
            forceEditing={forceEditing}
            notebookNodeType={notebookNodeType}
            options={options}
        />
    )
}

export function MountedRealNotebookNodeComponent({
    node,
    mode,
    notebookMode,
    updateProps,
    editOnly,
    forceEditing,
    notebookNodeType,
    options,
}: NotebookComponentRenderProps & {
    editOnly: boolean
    forceEditing: boolean
    notebookNodeType: NotebookNodeType
    options: CreatePostHogWidgetNodeOptions<any>
}): JSX.Element {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const contentRef = useRef<HTMLDivElement | null>(null)
    const attributes = useMemo(
        () => getNodeAttributes(node.props, node.id, options, notebookNodeType, forceEditing),
        [forceEditing, node.id, node.props, notebookNodeType, options]
    )
    const updateAttributes = useCallback(
        (nextAttributes: Partial<NotebookNodeAttributes<any>>): void => {
            updateProps(getSerializableProps(nextAttributes))
        },
        [updateProps]
    )
    const logicProps = useMemo(
        () => ({
            nodeType: notebookNodeType,
            notebookLogic: mountedNotebookLogic,
            attributes,
            updateAttributes,
            resizeable: options.resizeable,
            Settings: options.Settings ?? null,
            messageListeners: options.messageListeners,
            startExpanded: options.startExpanded,
            titlePlaceholder: options.titlePlaceholder,
            settingsPlacement: options.settingsPlacement,
        }),
        [attributes, mountedNotebookLogic, notebookNodeType, options, updateAttributes]
    )

    const nodeLogic = useMountedLogic(notebookNodeLogic(logicProps))
    const { setEditingNodeEditing } = useActions(notebookLogic)

    useEffect(() => {
        if (!forceEditing) {
            return
        }

        setEditingNodeEditing(attributes.nodeId, true)
        return () => setEditingNodeEditing(attributes.nodeId, false)
    }, [attributes.nodeId, forceEditing, setEditingNodeEditing])

    const Component = options.Component
    const Settings = options.Settings
    const showSettings = forceEditing && Settings
    const showContent = !editOnly || !Settings
    const isNotebookEditable = (notebookMode ?? mode) === 'edit'
    const isResizeable =
        isNotebookEditable &&
        (typeof options.resizeable === 'function' ? options.resizeable(attributes) : (options.resizeable ?? true))
    const contentStyle: CSSProperties | undefined =
        isResizeable || attributes.height
            ? { height: attributes.height ?? options.heightEstimate, minHeight: options.minHeight }
            : undefined

    // Native CSS resize writes to style.height; the new height is persisted on mouseup so the
    // table or visualization keeps its size after reloads.
    const handleResizeStart = useCallback((): void => {
        if (!isResizeable) {
            return
        }

        const initialHeight = contentRef.current?.style.height
        const handleResizeEnd = (): void => {
            window.removeEventListener('mouseup', handleResizeEnd)
            const nextHeight = contentRef.current?.style.height
            if (nextHeight && nextHeight !== initialHeight && contentRef.current) {
                updateAttributes({ height: contentRef.current.clientHeight })
            }
        }
        window.addEventListener('mouseup', handleResizeEnd)
    }, [isResizeable, updateAttributes])

    const handleResizeHandlePointerDown = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>): void => {
            if (!isResizeable || !contentRef.current) {
                return
            }

            event.preventDefault()
            event.stopPropagation()

            const element = contentRef.current
            const startY = event.clientY
            const startHeight = element.getBoundingClientRect().height
            const parsedMinHeight = Number.parseFloat(window.getComputedStyle(element).minHeight)
            const minHeight = Number.isFinite(parsedMinHeight) ? parsedMinHeight : 0

            const handlePointerMove = (moveEvent: PointerEvent): void => {
                moveEvent.preventDefault()
                const nextHeight = Math.max(minHeight, startHeight + moveEvent.clientY - startY)
                element.style.height = `${Math.round(nextHeight)}px`
            }

            const handlePointerUp = (): void => {
                window.removeEventListener('pointermove', handlePointerMove)
                window.removeEventListener('pointerup', handlePointerUp)
                updateAttributes({ height: element.clientHeight })
            }

            window.addEventListener('pointermove', handlePointerMove)
            window.addEventListener('pointerup', handlePointerUp)
        },
        [isResizeable, updateAttributes]
    )

    return (
        <NotebookNodeContext.Provider value={nodeLogic}>
            <BindLogic logic={notebookNodeLogic} props={logicProps}>
                <div className="MarkdownNotebook__real-node">
                    {showSettings ? (
                        <div className="MarkdownNotebook__real-node-settings">
                            <Settings attributes={attributes} updateAttributes={updateAttributes} />
                        </div>
                    ) : null}
                    {showContent ? (
                        <div
                            ref={contentRef}
                            className={clsx(
                                'MarkdownNotebook__real-node-content',
                                isResizeable && 'MarkdownNotebook__real-node-content--resizeable'
                            )}
                            style={contentStyle}
                            onMouseDown={handleResizeStart}
                        >
                            <Component attributes={attributes} updateAttributes={updateAttributes} />
                            {isResizeable ? (
                                <div
                                    className="MarkdownNotebook__real-node-resize-handle"
                                    aria-hidden="true"
                                    onPointerDown={handleResizeHandlePointerDown}
                                />
                            ) : null}
                        </div>
                    ) : null}
                </div>
            </BindLogic>
        </NotebookNodeContext.Provider>
    )
}

export function ImageEdit({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const alt = typeof node.props.alt === 'string' ? node.props.alt : ''

    return (
        <div className="MarkdownNotebook__component-form">
            <LemonInput
                value={src}
                onChange={(value) => updateProps({ src: value })}
                placeholder="Image URL"
                autoFocus={wasNotebookNodeJustInserted(node.id)}
            />
            <LemonInput value={alt} onChange={(value) => updateProps({ alt: value })} placeholder="Alt text" />
        </div>
    )
}

export function EmbedEdit({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const title = typeof node.props.title === 'string' ? node.props.title : ''

    return (
        <div className="MarkdownNotebook__component-form">
            <LemonInput
                value={title}
                onChange={(value) => updateProps({ title: value })}
                placeholder="Title"
                autoFocus={wasNotebookNodeJustInserted(node.id)}
            />
            <LemonInput
                value={src}
                onChange={(value) => updateProps({ src: value })}
                placeholder="Enter URL or iframe URL"
            />
        </div>
    )
}

export function LatexEdit({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const content = typeof node.props.content === 'string' ? node.props.content : ''

    return (
        <div className="MarkdownNotebook__component-form">
            <LemonTextArea
                value={content}
                onChange={(value) => updateProps({ content: value })}
                placeholder="E = mc^2"
                minRows={3}
                autoFocus={wasNotebookNodeJustInserted(node.id)}
            />
        </div>
    )
}

export function getNodeAttributes(
    props: NotebookComponentProps,
    fallbackNodeId: string,
    options: CreatePostHogWidgetNodeOptions<any> | null,
    nodeType: NotebookNodeType | undefined,
    forceEditing: boolean
): NotebookNodeAttributes<any> {
    const attributeProps = getNodeAttributeProps(props)
    const attributes = {
        ...getDefaultProps(options),
        ...attributeProps,
        nodeId: typeof props.nodeId === 'string' ? props.nodeId : fallbackNodeId,
    } as NotebookNodeAttributes<any>

    if (nodeType === NotebookNodeType.Latex && !forceEditing) {
        attributes.editing = false
    }

    return attributes
}

export function getNodeAttributeProps(props: NotebookComponentProps): NotebookComponentProps {
    return Object.entries(props).reduce<NotebookComponentProps>((attributeProps, [key, value]) => {
        if (key !== 'view' && key !== 'edit' && key !== 'hideFilters' && key !== 'hideResults') {
            attributeProps[key] = value
        }
        return attributeProps
    }, {})
}

export function getDefaultProps(options: CreatePostHogWidgetNodeOptions<any> | null): NotebookComponentProps {
    return (
        Object.entries(options?.attributes ?? {}) as [string, { default?: unknown }][]
    ).reduce<NotebookComponentProps>((props, [key, config]) => {
        const defaultValue = config.default
        if (isNotebookPropValue(defaultValue)) {
            props[key] = defaultValue
        }
        return props
    }, {})
}

export function getDefaultPropsForNodeType(nodeType: NotebookNodeType | undefined): NotebookComponentProps {
    return getDefaultProps(nodeType ? KNOWN_NODES[nodeType] : null)
}

export function getSerializableProps(attributes: Partial<NotebookNodeAttributes<any>>): NotebookComponentProps {
    return Object.entries(attributes).reduce<NotebookComponentProps>((props, [key, value]) => {
        if (value !== undefined && isNotebookPropValue(value)) {
            props[key] = value as NotebookPropValue
        }
        return props
    }, {})
}

export function splitTagName(tagName: string): string {
    return tagName.replace(/([a-z])([A-Z])/g, '$1 $2')
}
