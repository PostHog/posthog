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

import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { MarkdownNotebook, createMarkdownNotebookRegistry } from 'lib/components/MarkdownNotebook'
import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import {
    NotebookComponentDefinition,
    NotebookComponentProps,
    NotebookComponentRenderProps,
    NotebookComponentRegistry,
    NotebookPropValue,
} from 'lib/components/MarkdownNotebook/types'
import { isNotebookPropValue } from 'lib/components/MarkdownNotebook/utils'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxContextType } from 'scenes/max/maxTypes'
import type { MaxUIContext } from 'scenes/max/maxTypes'

import { NODE_ICONS } from '../nodeIcons'
import { NotebookNodeContext } from '../Nodes/NotebookNodeContext'
import { notebookNodeLogic } from '../Nodes/notebookNodeLogic'
import { CreatePostHogWidgetNodeOptions, NotebookNodeAttributes, NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import {
    buildMarkdownNotebookContent,
    getMarkdownNotebookMarkdown,
    getMarkdownNotebookNodeId,
} from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

const MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE: Partial<Record<string, NotebookNodeType>> = {
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

const MARKDOWN_NODE_DEFINITIONS: {
    tagName: string
    category: string
    label?: string
    EditComponent?: NotebookComponentDefinition['EditComponent']
    exclusiveEditPanel?: boolean
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

export function MarkdownNotebookV2(): JSX.Element {
    const { content, isEditable, notebook } = useValues(notebookLogic)
    const { setLocalContent, setAutosavePaused } = useActions(notebookLogic)
    const { openSidePanelMax } = useActions(maxGlobalLogic)
    const { askMax } = useActions(maxLogic({ tabId: 'sidepanel' }))
    const markdown = getMarkdownNotebookMarkdown(content)
    const remoteMarkdown = getMarkdownNotebookMarkdown(notebook?.content)
    const nodeId = getMarkdownNotebookNodeId(content)
    const [isInteractionActive, setIsInteractionActive] = useState(false)
    const [draftMarkdown, setDraftMarkdown] = useState<string | null>(null)
    const isInteractionActiveRef = useRef(false)
    const latestMarkdownRef = useRef(markdown)
    const bufferedMarkdownRef = useRef<string | null>(null)
    const nodeIdRef = useRef(nodeId)
    const renderedMarkdown = draftMarkdown ?? markdown

    useEffect(() => {
        if (draftMarkdown === null) {
            latestMarkdownRef.current = markdown
        } else if (draftMarkdown === markdown) {
            latestMarkdownRef.current = markdown
            setDraftMarkdown(null)
        }
    }, [markdown, draftMarkdown])

    useEffect(() => {
        nodeIdRef.current = nodeId
    }, [nodeId])

    const flushBufferedMarkdown = useCallback((): void => {
        const bufferedMarkdown = bufferedMarkdownRef.current
        if (bufferedMarkdown === null) {
            return
        }

        bufferedMarkdownRef.current = null
        if (bufferedMarkdown === latestMarkdownRef.current) {
            return
        }

        latestMarkdownRef.current = bufferedMarkdown
        setLocalContent(buildMarkdownNotebookContent(bufferedMarkdown, nodeIdRef.current))
    }, [setLocalContent])

    const handleChange = useCallback(
        (nextMarkdown: string): void => {
            if (isInteractionActiveRef.current) {
                bufferedMarkdownRef.current = nextMarkdown
                setDraftMarkdown(nextMarkdown)
                return
            }

            if (nextMarkdown === latestMarkdownRef.current) {
                return
            }

            latestMarkdownRef.current = nextMarkdown
            setLocalContent(buildMarkdownNotebookContent(nextMarkdown, nodeIdRef.current))
        },
        [setLocalContent]
    )
    const handleInteractionStateChange = useCallback(
        (nextIsInteractionActive: boolean): void => {
            if (isInteractionActiveRef.current === nextIsInteractionActive) {
                return
            }

            isInteractionActiveRef.current = nextIsInteractionActive
            setIsInteractionActive(nextIsInteractionActive)
            if (nextIsInteractionActive) {
                setDraftMarkdown(latestMarkdownRef.current)
                setAutosavePaused(true)
                return
            }

            const hadBufferedMarkdown = bufferedMarkdownRef.current !== null
            flushBufferedMarkdown()
            if (!hadBufferedMarkdown) {
                setDraftMarkdown(null)
            }
            setAutosavePaused(false)
        },
        [flushBufferedMarkdown, setAutosavePaused]
    )
    const handleAskAI = useCallback(
        ({ query, placeholderNodeId, markdownWithPlaceholder }: MarkdownNotebookAskAIRequest): void => {
            const notebookShortId = notebook?.short_id
            const notebookTitle = notebook?.title ?? 'Untitled notebook'
            const uiContext: Partial<MaxUIContext> | undefined = notebookShortId
                ? {
                      notebooks: [
                          {
                              type: MaxContextType.NOTEBOOK,
                              id: notebookShortId,
                              name: notebookTitle,
                          },
                      ],
                  }
                : undefined

            openSidePanelMax()
            window.setTimeout(() => {
                askMax(
                    buildNotebookAskAIPrompt({
                        query,
                        placeholderNodeId,
                        markdownWithPlaceholder,
                        notebookShortId,
                        notebookTitle,
                    }),
                    true,
                    uiContext
                )
            }, 100)
        },
        [askMax, notebook?.short_id, notebook?.title, openSidePanelMax]
    )

    return (
        <MarkdownNotebook
            value={renderedMarkdown}
            remoteValue={remoteMarkdown}
            mode={isEditable ? 'edit' : 'view'}
            registry={NOTEBOOK_MARKDOWN_REGISTRY}
            onChange={isEditable ? handleChange : undefined}
            onAskAI={isEditable ? handleAskAI : undefined}
            deferRemoteValue={isInteractionActive}
            onInteractionStateChange={handleInteractionStateChange}
            className="Notebook__markdown-v2"
            data-attr="notebook-markdown-v2"
            autoFocus={isEditable}
        />
    )
}

function buildNotebookAskAIPrompt({
    query,
    placeholderNodeId,
    markdownWithPlaceholder,
    notebookShortId,
    notebookTitle,
}: {
    query: string
    placeholderNodeId: string
    markdownWithPlaceholder: string
    notebookShortId?: string
    notebookTitle: string
}): string {
    const notebookReference = notebookShortId
        ? `Notebook short_id: ${notebookShortId}`
        : 'Notebook short_id: unavailable in the UI'

    return `The user is asking from a Markdown notebook v2 editor.
${notebookReference}
Notebook title: ${notebookTitle}
AI insertion placeholder block id: ${placeholderNodeId}

The placeholder block is currently shown in the notebook as "Thinking ...". In the markdown below, the exact insertion point is marked with \`<!-- Ask PostHog AI insertion placeholder -->\`. If the user says "here", "this spot", "below", "above", or similar, they mean this placeholder location. Use notebook tools against the current notebook when changing notebook content. For Markdown notebook v2, preserve the single ph-markdown-notebook node and update its attrs.markdown with valid markdown instead of replacing it with legacy rich-text blocks.

Current notebook markdown with insertion placeholder:
\`\`\`markdown
${markdownWithPlaceholder}
\`\`\`

User request:
${query}`
}

const NOTEBOOK_MARKDOWN_REGISTRY: NotebookComponentRegistry = createMarkdownNotebookRegistry(
    MARKDOWN_NODE_DEFINITIONS.map((definition) => {
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
        }
    })
)

function RealNotebookNodeView(props: NotebookComponentRenderProps): JSX.Element {
    return <RealNotebookNodeComponent {...props} />
}

function RealNotebookNodeEdit(props: NotebookComponentRenderProps): JSX.Element {
    return <RealNotebookNodeComponent {...props} forceEditing editOnly />
}

function RealNotebookNodeComponent({
    node,
    updateProps,
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
            mode={forceEditing ? 'edit' : 'view'}
            updateProps={updateProps}
            editOnly={editOnly}
            forceEditing={forceEditing}
            notebookNodeType={notebookNodeType}
            options={options}
        />
    )
}

function MountedRealNotebookNodeComponent({
    node,
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
                        <div className="MarkdownNotebook__real-node-content">
                            <Component attributes={attributes} updateAttributes={updateAttributes} />
                        </div>
                    ) : null}
                </div>
            </BindLogic>
        </NotebookNodeContext.Provider>
    )
}

function ImageEdit({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const alt = typeof node.props.alt === 'string' ? node.props.alt : ''

    return (
        <div className="MarkdownNotebook__component-form">
            <LemonInput
                value={src}
                onChange={(value) => updateProps({ src: value })}
                placeholder="Image URL"
                autoFocus
            />
            <LemonInput value={alt} onChange={(value) => updateProps({ alt: value })} placeholder="Alt text" />
        </div>
    )
}

function EmbedEdit({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const title = typeof node.props.title === 'string' ? node.props.title : ''

    return (
        <div className="MarkdownNotebook__component-form">
            <LemonInput
                value={src}
                onChange={(value) => updateProps({ src: value })}
                placeholder="Enter URL or iframe URL"
                autoFocus
            />
            <LemonInput value={title} onChange={(value) => updateProps({ title: value })} placeholder="Title" />
        </div>
    )
}

function LatexEdit({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const content = typeof node.props.content === 'string' ? node.props.content : ''

    return (
        <div className="MarkdownNotebook__component-form">
            <LemonTextArea
                value={content}
                onChange={(value) => updateProps({ content: value })}
                placeholder="E = mc^2"
                minRows={3}
                autoFocus
            />
        </div>
    )
}

function getNodeAttributes(
    props: NotebookComponentProps,
    fallbackNodeId: string,
    options: CreatePostHogWidgetNodeOptions<any> | null,
    nodeType: NotebookNodeType | undefined,
    forceEditing: boolean
): NotebookNodeAttributes<any> {
    const attributes = {
        ...getDefaultProps(options),
        ...props,
        nodeId: typeof props.nodeId === 'string' ? props.nodeId : fallbackNodeId,
    } as NotebookNodeAttributes<any>

    if (nodeType === NotebookNodeType.Latex && !forceEditing) {
        attributes.editing = false
    }

    return attributes
}

function getDefaultProps(options: CreatePostHogWidgetNodeOptions<any> | null): NotebookComponentProps {
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

function getDefaultPropsForNodeType(nodeType: NotebookNodeType | undefined): NotebookComponentProps {
    return getDefaultProps(nodeType ? KNOWN_NODES[nodeType] : null)
}

function getSerializableProps(attributes: Partial<NotebookNodeAttributes<any>>): NotebookComponentProps {
    return Object.entries(attributes).reduce<NotebookComponentProps>((props, [key, value]) => {
        if (value !== undefined && isNotebookPropValue(value)) {
            props[key] = value as NotebookPropValue
        }
        return props
    }, {})
}

function splitTagName(tagName: string): string {
    return tagName.replace(/([a-z])([A-Z])/g, '$1 $2')
}
