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
import { createContext, type CSSProperties, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

import { IconMessage, IconSend, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { MarkdownNotebook, createMarkdownNotebookRegistry } from 'lib/components/MarkdownNotebook'
import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import {
    NotebookComponentBlockNode,
    NotebookComponentDefinition,
    NotebookComponentProps,
    NotebookComponentRenderProps,
    NotebookComponentRegistry,
    NotebookPropValue,
} from 'lib/components/MarkdownNotebook/types'
import { isNotebookPropValue } from 'lib/components/MarkdownNotebook/utils'
import { uuid } from 'lib/utils'
import { MarkdownMessage } from 'scenes/max/MarkdownMessage'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import type { maxLogicType } from 'scenes/max/maxLogicType'
import { MaxThreadLogicProps, ThreadMessage, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { MaxContextType } from 'scenes/max/maxTypes'
import type { MaxUIContext } from 'scenes/max/maxTypes'

import {
    ArtifactContentType,
    type ArtifactMessage,
    AssistantMessageType,
    type NotebookArtifactContent,
} from '~/queries/schema/schema-assistant-messages'

import { NODE_ICONS } from '../nodeIcons'
import { NotebookNodeContext } from '../Nodes/NotebookNodeContext'
import { notebookNodeLogic } from '../Nodes/notebookNodeLogic'
import { CreatePostHogWidgetNodeOptions, NotebookNodeAttributes, NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import {
    buildMarkdownNotebookContent,
    getMarkdownNotebookMarkdown,
    getMarkdownNotebookNodeId,
    notebookArtifactContentToMarkdown,
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

type InlineNotebookAIRequest = MarkdownNotebookAskAIRequest & {
    panelId: string
    uiContext?: Partial<MaxUIContext>
}

type NotebookArtifactThreadMessage = ArtifactMessage &
    ThreadMessage & {
        content: NotebookArtifactContent
    }

type MarkdownNotebookRuntimeContextValue = {
    notebookShortId: string | null
    notebookTitle: string
    markdown: string
    applyNotebookArtifactContent: (content: NotebookArtifactContent, chatId?: string) => void
}

const MarkdownNotebookRuntimeContext = createContext<MarkdownNotebookRuntimeContextValue | null>(null)

export function MarkdownNotebookV2(): JSX.Element {
    const { content, isEditable, notebook } = useValues(notebookLogic)
    const { setLocalContent, setAutosavePaused } = useActions(notebookLogic)
    const markdown = getMarkdownNotebookMarkdown(content)
    const remoteMarkdown = getMarkdownNotebookMarkdown(notebook?.content)
    const nodeId = getMarkdownNotebookNodeId(content)
    const [isInteractionActive, setIsInteractionActive] = useState(false)
    const [draftMarkdown, setDraftMarkdown] = useState<string | null>(null)
    const [inlineAIRequests, setInlineAIRequests] = useState<InlineNotebookAIRequest[]>([])
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
        ({
            chatId,
            query,
            source,
            chatNodeId,
            chatMarker,
            markdown,
            markdownWithChat,
            selectedMarkdown,
        }: MarkdownNotebookAskAIRequest): void => {
            const uiContext = getNotebookAIChatUIContext({
                notebookShortId: notebook?.short_id ?? null,
                notebookTitle: notebook?.title ?? 'Untitled notebook',
                markdown: markdownWithChat,
                chatId,
                chatMarker,
            })

            const inlineAIRequest: InlineNotebookAIRequest = {
                chatId,
                panelId: getInlineNotebookAIPanelId(chatId, 'inline'),
                query,
                source,
                chatNodeId,
                chatMarker,
                markdown,
                markdownWithChat,
                selectedMarkdown,
                uiContext,
            }
            setInlineAIRequests((currentRequests) => [
                ...currentRequests.filter((currentRequest) => currentRequest.chatId !== chatId),
                inlineAIRequest,
            ])
        },
        [notebook?.short_id, notebook?.title]
    )

    const applyNotebookArtifactContent = useCallback(
        (content: NotebookArtifactContent, chatId?: string): void => {
            const artifactMarkdown = notebookArtifactContentToMarkdown(content)
            if (!artifactMarkdown.trim()) {
                return
            }

            const nextMarkdown = preserveNotebookAIChatMarker(artifactMarkdown, latestMarkdownRef.current, chatId)
            if (nextMarkdown === latestMarkdownRef.current) {
                return
            }

            bufferedMarkdownRef.current = null
            latestMarkdownRef.current = nextMarkdown
            setDraftMarkdown(null)
            setAutosavePaused(false)
            setLocalContent(buildMarkdownNotebookContent(nextMarkdown, nodeIdRef.current))
        },
        [setAutosavePaused, setLocalContent]
    )

    const runtimeContext = useMemo<MarkdownNotebookRuntimeContextValue>(
        () => ({
            notebookShortId: notebook?.short_id ?? null,
            notebookTitle: notebook?.title ?? 'Untitled notebook',
            markdown: renderedMarkdown,
            applyNotebookArtifactContent,
        }),
        [applyNotebookArtifactContent, notebook?.short_id, notebook?.title, renderedMarkdown]
    )

    const handleInlineAIComplete = useCallback((request: InlineNotebookAIRequest): void => {
        window.setTimeout(() => {
            setInlineAIRequests((currentRequests) =>
                currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
            )
        }, 0)
    }, [])

    const handleInlineAIError = useCallback((request: InlineNotebookAIRequest): void => {
        setInlineAIRequests((currentRequests) =>
            currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
        )
    }, [])

    return (
        <MarkdownNotebookRuntimeContext.Provider value={runtimeContext}>
            <MarkdownNotebook
                value={renderedMarkdown}
                remoteValue={remoteMarkdown}
                mode={isEditable ? 'edit' : 'view'}
                registry={NOTEBOOK_MARKDOWN_REGISTRY}
                onChange={isEditable ? handleChange : undefined}
                onAskAI={isEditable ? handleAskAI : undefined}
                createAIChatId={uuid}
                deferRemoteValue={isInteractionActive}
                onInteractionStateChange={handleInteractionStateChange}
                className="Notebook__markdown-v2"
                data-attr="notebook-markdown-v2"
                autoFocus={isEditable}
                showDebug={isEditable}
            />
            {inlineAIRequests.map((request) => (
                <InlineNotebookAIRunner
                    key={request.chatId}
                    request={request}
                    onComplete={handleInlineAIComplete}
                    onError={handleInlineAIError}
                />
            ))}
        </MarkdownNotebookRuntimeContext.Provider>
    )
}

function InlineNotebookAIRunner({
    request,
    onComplete,
    onError,
}: {
    request: InlineNotebookAIRequest
    onComplete: (request: InlineNotebookAIRequest) => void
    onError: (request: InlineNotebookAIRequest) => void
}): JSX.Element {
    const maxLogicProps = useMemo<maxLogicType['props']>(
        () => ({ panelId: request.panelId, initialFrontendConversationId: request.chatId, syncUrl: false }),
        [request.chatId, request.panelId]
    )
    const maxLogicInstance = maxLogic(maxLogicProps)
    useMountedLogic(maxLogicInstance)

    const { askMax } = useActions(maxLogicInstance)
    const { threadLogicProps } = useValues(maxLogicInstance)

    if (threadLogicProps.conversationId !== request.chatId) {
        return <></>
    }

    return (
        <InlineNotebookAIThread
            request={request}
            threadLogicProps={threadLogicProps}
            askMax={askMax}
            onComplete={onComplete}
            onError={onError}
        />
    )
}

function InlineNotebookAIThread({
    request,
    threadLogicProps,
    askMax,
    onComplete,
    onError,
}: {
    request: InlineNotebookAIRequest
    threadLogicProps: MaxThreadLogicProps
    askMax: (prompt: string | null, addToThread?: boolean, uiContext?: Partial<MaxUIContext>) => void
    onComplete: (request: InlineNotebookAIRequest) => void
    onError: (request: InlineNotebookAIRequest) => void
}): null {
    const threadLogicInstance = maxThreadLogic(threadLogicProps)
    useMountedLogic(threadLogicInstance)

    const { threadRaw, threadLoading } = useValues(threadLogicInstance)
    const didAskRef = useRef(false)
    const didCompleteRef = useRef(false)
    useApplyNotebookArtifactMessages(threadRaw, request.chatId)

    useEffect(() => {
        if (didAskRef.current) {
            return
        }

        didAskRef.current = true
        askMax(request.query, true, request.uiContext)
    }, [askMax, request])

    useEffect(() => {
        if (!didAskRef.current || didCompleteRef.current || threadLoading) {
            return
        }

        const completion = getInlineAICompletion(threadRaw)
        if (!completion) {
            return
        }

        didCompleteRef.current = true
        if (completion.status === 'error') {
            onError(request)
            return
        }

        onComplete(request)
    }, [onComplete, onError, request, threadLoading, threadRaw])

    return null
}

function getInlineAICompletion(threadRaw: ThreadMessage[]): { status: 'done' | 'error'; message: string } | null {
    const lastErrorMessage = [...threadRaw]
        .reverse()
        .find((message) => message.type === AssistantMessageType.Failure || message.status === 'error')
    if (lastErrorMessage) {
        return {
            status: 'error',
            message: getInlineAIStatusText(
                'content' in lastErrorMessage && typeof lastErrorMessage.content === 'string'
                    ? lastErrorMessage.content
                    : undefined,
                'PostHog AI could not finish this request.'
            ),
        }
    }

    const completedMessages = threadRaw.filter((message) => message.status === 'completed')
    const lastAssistantMessage = [...completedMessages]
        .reverse()
        .find((message) => message.type !== AssistantMessageType.Human)
    if (!lastAssistantMessage) {
        return null
    }

    if (lastAssistantMessage.type === AssistantMessageType.Assistant) {
        return {
            status: 'done',
            message: getInlineAIStatusText(lastAssistantMessage.content, 'PostHog AI finished.'),
        }
    }

    if (lastAssistantMessage.type === AssistantMessageType.Notebook) {
        return {
            status: 'done',
            message: 'Updated the notebook.',
        }
    }

    return {
        status: 'done',
        message: 'PostHog AI finished.',
    }
}

function getInlineAIStatusText(value: string | undefined, fallback: string): string {
    const oneLineValue = value?.replace(/\s+/g, ' ').trim()
    if (!oneLineValue) {
        return fallback
    }
    return oneLineValue.length > 160 ? `${oneLineValue.slice(0, 157)}...` : oneLineValue
}

function useApplyNotebookArtifactMessages(threadRaw: ThreadMessage[], chatId: string): void {
    const runtimeContext = useContext(MarkdownNotebookRuntimeContext)
    const appliedArtifactKeysRef = useRef<Set<string>>(new Set())

    useEffect(() => {
        if (!runtimeContext) {
            return
        }

        for (const message of threadRaw) {
            if (!isCompletedNotebookArtifactMessage(message)) {
                continue
            }

            const artifactKey = getNotebookArtifactMessageKey(message)
            if (appliedArtifactKeysRef.current.has(artifactKey)) {
                continue
            }

            runtimeContext.applyNotebookArtifactContent(message.content, chatId)
            appliedArtifactKeysRef.current.add(artifactKey)
        }
    }, [chatId, runtimeContext, threadRaw])
}

function isCompletedNotebookArtifactMessage(message: ThreadMessage): message is NotebookArtifactThreadMessage {
    return (
        message.type === AssistantMessageType.Artifact &&
        message.status === 'completed' &&
        message.content.content_type === ArtifactContentType.Notebook
    )
}

function getNotebookArtifactMessageKey(message: NotebookArtifactThreadMessage): string {
    return `${message.artifact_id}:${message.id ?? ''}:${JSON.stringify(message.content.blocks)}`
}

const NOTEBOOK_MARKDOWN_REGISTRY: NotebookComponentRegistry = createMarkdownNotebookRegistry([
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
])

function getMarkdownNotebookNodeTitle(
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

function getNotebookAIChatTitle(node: NotebookComponentBlockNode): string | null {
    return (
        getNotebookStringProp(node.props.title) ??
        summarizeTitle(getNotebookStringProp(node.props.lastAnswer) ?? getNotebookStringProp(node.props.answer))
    )
}

function getNotebookAIChatUIContext({
    notebookShortId,
    notebookTitle,
    markdown,
    chatId,
    chatMarker = getNotebookAIChatMarker(chatId),
}: {
    notebookShortId: string | null
    notebookTitle: string
    markdown: string
    chatId: string
    chatMarker?: string
}): Partial<MaxUIContext> | undefined {
    if (!notebookShortId) {
        return undefined
    }

    return {
        notebooks: [
            {
                type: MaxContextType.NOTEBOOK,
                id: notebookShortId,
                name: notebookTitle,
                markdown_with_insertion_placeholder: markdown,
                insertion_placeholder_block_id: chatId,
                insertion_placeholder_marker: chatMarker,
            },
        ],
    }
}

function preserveNotebookAIChatMarker(
    nextMarkdown: string,
    currentMarkdown: string,
    chatId: string | undefined
): string {
    if (!chatId) {
        return nextMarkdown
    }

    const chatMarker = getNotebookAIChatMarker(chatId)
    if (!currentMarkdown.includes(chatMarker) || nextMarkdown.includes(chatMarker)) {
        return nextMarkdown
    }

    return [nextMarkdown.trimEnd(), chatMarker].filter((block) => block.trim()).join('\n\n')
}

function getNotebookAIChatMarker(chatId: string): string {
    return `<Chat id="${chatId}" />`
}

function getInlineNotebookAIPanelId(chatId: string, mode: 'inline' | 'full'): string {
    return `notebook-inline-${mode}-${chatId}`
}

function getNotebookStringProp(value: NotebookPropValue | undefined): string | null {
    return typeof value === 'string' ? value : null
}

function getNotebookObjectProp(value: NotebookPropValue | undefined): Record<string, NotebookPropValue> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function getUnknownStringProp(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

function getQueryTitle(queryValue: unknown): string | null {
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

function getSeriesTitle(query: Record<string, NotebookPropValue>): string | null {
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

function summarizeTitle(value: string | null | undefined): string | null {
    const oneLineValue = value?.replace(/\s+/g, ' ').trim()
    if (!oneLineValue) {
        return null
    }
    return oneLineValue.length > 120 ? `${oneLineValue.slice(0, 117)}...` : oneLineValue
}

function NotebookAIChat({ node, updateProps, deleteNode }: NotebookComponentRenderProps): JSX.Element {
    const cachedLastAnswer = getNotebookStringProp(node.props.lastAnswer) ?? getNotebookStringProp(node.props.answer)
    const hasLegacyAnswer = node.props.answer !== undefined
    const chatId = getNotebookStringProp(node.props.id)
    const cachedTitle = getNotebookStringProp(node.props.title)
    const hasPersistedMessages = node.props.messages !== undefined
    const shouldStartActive = !cachedLastAnswer
    const [isThreadActive, setIsThreadActive] = useState(shouldStartActive)
    const [loadOlderMessages, setLoadOlderMessages] = useState(false)
    const [queuedReply, setQueuedReply] = useState<string | null>(null)
    const [activeBaseMessages, setActiveBaseMessages] = useState<NotebookAIChatMessage[]>(() =>
        shouldStartActive ? getNotebookAIChatBaseMessages(cachedLastAnswer) : []
    )

    useEffect(() => {
        if (hasPersistedMessages) {
            updateProps({ messages: undefined })
        }
    }, [hasPersistedMessages, updateProps])

    if (!chatId) {
        return <div className="MarkdownNotebook__component-preview">Missing AI chat id.</div>
    }

    if (cachedLastAnswer && !isThreadActive) {
        const baseMessages = getNotebookAIChatBaseMessages(cachedLastAnswer)

        return (
            <NotebookAIChatConversation
                messages={baseMessages}
                canReply
                showOlderMessages
                onShowOlderMessages={() => {
                    setActiveBaseMessages(baseMessages)
                    setLoadOlderMessages(true)
                    setIsThreadActive(true)
                }}
                onReply={(reply) => {
                    setActiveBaseMessages(baseMessages)
                    setQueuedReply(reply)
                    setIsThreadActive(true)
                }}
                onDismiss={deleteNode}
            />
        )
    }

    return (
        <NotebookAIChatById
            chatId={chatId}
            cachedTitle={cachedTitle}
            cachedLastAnswer={cachedLastAnswer}
            baseMessages={activeBaseMessages}
            hasLegacyAnswer={hasLegacyAnswer}
            loadOlderMessages={loadOlderMessages}
            queuedReply={queuedReply}
            onShowOlderMessages={() => setLoadOlderMessages(true)}
            onCollapseOlderMessages={() => {
                setActiveBaseMessages(getNotebookAIChatBaseMessages(cachedLastAnswer))
                setLoadOlderMessages(false)
                setQueuedReply(null)
                setIsThreadActive(false)
            }}
            onQueuedReplyConsumed={() => setQueuedReply(null)}
            updateProps={updateProps}
            onDismiss={deleteNode}
        />
    )
}

function NotebookAIChatById({
    chatId,
    cachedTitle,
    cachedLastAnswer,
    baseMessages,
    hasLegacyAnswer,
    loadOlderMessages,
    queuedReply,
    onShowOlderMessages,
    onCollapseOlderMessages,
    onQueuedReplyConsumed,
    updateProps,
    onDismiss,
}: {
    chatId: string
    cachedTitle: string | null
    cachedLastAnswer: string | null
    baseMessages: NotebookAIChatMessage[]
    hasLegacyAnswer: boolean
    loadOlderMessages: boolean
    queuedReply: string | null
    onShowOlderMessages: () => void
    onCollapseOlderMessages: () => void
    onQueuedReplyConsumed: () => void
    updateProps: (props: Partial<NotebookComponentProps>) => void
    onDismiss: () => void
}): JSX.Element {
    const panelId = getInlineNotebookAIPanelId(chatId, loadOlderMessages ? 'full' : 'inline')
    const maxLogicProps = useMemo<maxLogicType['props']>(
        () => ({ panelId, initialFrontendConversationId: chatId, syncUrl: false }),
        [chatId, panelId]
    )
    const maxLogicInstance = maxLogic(maxLogicProps)
    useMountedLogic(maxLogicInstance)

    const { setConversationId } = useActions(maxLogicInstance)
    const { loadConversation } = useActions(maxGlobalLogic)
    const { threadLogicProps } = useValues(maxLogicInstance)

    useEffect(() => {
        if (loadOlderMessages) {
            setConversationId(chatId)
            loadConversation(chatId)
            return
        }

        const timeout = window.setTimeout(() => {
            if (!maxLogicInstance.values.conversationId && maxLogicInstance.values.activeStreamingThreads === 0) {
                setConversationId(chatId)
            }
        }, 1500)
        return () => window.clearTimeout(timeout)
    }, [chatId, loadConversation, loadOlderMessages, maxLogicInstance, setConversationId])

    if (threadLogicProps.conversationId !== chatId) {
        return (
            <NotebookAIChatConversation
                messages={[{ role: 'thinking', id: 'notebook-ai-chat-loading', content: 'Thinking ...' }]}
                canReply={false}
                showOlderMessages={false}
            />
        )
    }

    return (
        <NotebookAIChatThread
            chatId={chatId}
            threadLogicProps={{ ...threadLogicProps, skipInitialLoad: !loadOlderMessages }}
            cachedTitle={cachedTitle}
            cachedLastAnswer={cachedLastAnswer}
            baseMessages={baseMessages}
            hasLegacyAnswer={hasLegacyAnswer}
            loadOlderMessages={loadOlderMessages}
            queuedReply={queuedReply}
            onShowOlderMessages={onShowOlderMessages}
            onCollapseOlderMessages={onCollapseOlderMessages}
            onQueuedReplyConsumed={onQueuedReplyConsumed}
            updateProps={updateProps}
            onDismiss={onDismiss}
        />
    )
}

function NotebookAIChatThread({
    chatId,
    threadLogicProps,
    cachedTitle,
    cachedLastAnswer,
    baseMessages,
    hasLegacyAnswer,
    loadOlderMessages,
    queuedReply,
    onShowOlderMessages,
    onCollapseOlderMessages,
    onQueuedReplyConsumed,
    updateProps,
    onDismiss,
}: {
    chatId: string
    threadLogicProps: MaxThreadLogicProps
    cachedTitle: string | null
    cachedLastAnswer: string | null
    baseMessages: NotebookAIChatMessage[]
    hasLegacyAnswer: boolean
    loadOlderMessages: boolean
    queuedReply: string | null
    onShowOlderMessages: () => void
    onCollapseOlderMessages: () => void
    onQueuedReplyConsumed: () => void
    updateProps: (props: Partial<NotebookComponentProps>) => void
    onDismiss: () => void
}): JSX.Element {
    const threadLogicInstance = maxThreadLogic(threadLogicProps)
    useMountedLogic(threadLogicInstance)

    const { askMax } = useActions(threadLogicInstance)
    const { conversation, threadGrouped, threadLoading, threadRaw } = useValues(threadLogicInstance)
    const runtimeContext = useContext(MarkdownNotebookRuntimeContext)
    const replyUiContext = useMemo(
        () =>
            getNotebookAIChatUIContext({
                notebookShortId: runtimeContext?.notebookShortId ?? null,
                notebookTitle: runtimeContext?.notebookTitle ?? 'Untitled notebook',
                markdown: runtimeContext?.markdown ?? '',
                chatId,
            }),
        [chatId, runtimeContext?.markdown, runtimeContext?.notebookShortId, runtimeContext?.notebookTitle]
    )
    const threadMessages = getNotebookAIChatThreadMessages(threadGrouped, threadLoading)
    const visibleMessages =
        loadOlderMessages && threadMessages.length > 0 ? threadMessages : [...baseMessages, ...threadMessages]
    const displayMessages =
        visibleMessages.length > 0
            ? visibleMessages
            : [{ role: 'thinking' as const, id: 'notebook-ai-chat-loading', content: 'Thinking ...' }]
    const conversationTitle = getUnknownStringProp(conversation?.title)
    const latestAnswer = getLatestNotebookAIChatAnswer(visibleMessages)
    const isThinking = threadLoading || displayMessages.at(-1)?.role === 'thinking'
    useApplyNotebookArtifactMessages(threadRaw, chatId)

    useEffect(() => {
        if (!queuedReply) {
            return
        }

        askMax(queuedReply, true, replyUiContext)
        onQueuedReplyConsumed()
    }, [askMax, onQueuedReplyConsumed, queuedReply, replyUiContext])

    useEffect(() => {
        const nextProps: Partial<NotebookComponentProps> = {}

        if (latestAnswer && latestAnswer !== cachedLastAnswer) {
            nextProps.lastAnswer = latestAnswer
        }
        if (hasLegacyAnswer && latestAnswer) {
            nextProps.answer = undefined
        }
        if (conversationTitle && conversationTitle !== cachedTitle) {
            nextProps.title = conversationTitle
        }

        if (Object.keys(nextProps).length > 0) {
            updateProps(nextProps)
        }
    }, [cachedLastAnswer, cachedTitle, conversationTitle, hasLegacyAnswer, latestAnswer, updateProps])

    return (
        <NotebookAIChatConversation
            messages={displayMessages}
            canReply={!isThinking}
            showOlderMessages={!loadOlderMessages && baseMessages.length > 0}
            showCollapseOlderMessages={loadOlderMessages}
            onShowOlderMessages={onShowOlderMessages}
            onCollapseOlderMessages={onCollapseOlderMessages}
            onReply={(reply) => askMax(reply, true, replyUiContext)}
            onDismiss={onDismiss}
        />
    )
}

function NotebookAIChatAnswer({
    id,
    content,
    compact = false,
}: {
    id: string
    content: string
    compact?: boolean
}): JSX.Element {
    return (
        <div
            className={
                compact
                    ? 'MarkdownNotebook__ai-chat-answer MarkdownNotebook__ai-chat-answer--compact'
                    : 'MarkdownNotebook__ai-chat-answer'
            }
        >
            <MarkdownMessage content={content} id={id} />
        </div>
    )
}

function NotebookAIChatThinking({ message }: { message: string }): JSX.Element {
    return (
        <div className="MarkdownNotebook__ai-chat-thinking">
            <IconSparkles />
            <span>{message}</span>
        </div>
    )
}

type NotebookAIChatMessageRole = 'human' | 'assistant' | 'thinking' | 'error'

type NotebookAIChatMessage = {
    role: NotebookAIChatMessageRole
    content: string
    id?: string
}

function NotebookAIChatConversation({
    messages,
    canReply,
    showOlderMessages,
    showCollapseOlderMessages = false,
    onShowOlderMessages,
    onCollapseOlderMessages,
    onReply,
    onDismiss,
}: {
    messages: NotebookAIChatMessage[]
    canReply: boolean
    showOlderMessages: boolean
    showCollapseOlderMessages?: boolean
    onShowOlderMessages?: () => void
    onCollapseOlderMessages?: () => void
    onReply?: (reply: string) => void
    onDismiss?: () => void
}): JSX.Element {
    const [isReplying, setIsReplying] = useState(false)
    const [reply, setReply] = useState('')
    const scrollRef = useRef<HTMLDivElement>(null)
    const replyText = reply.trim()
    const canSubmit = canReply && !!replyText && !!onReply
    const messageFingerprint = messages
        .map((message) => `${message.role}:${message.id ?? ''}:${message.content}`)
        .join('|')

    useEffect(() => {
        const scrollElement = scrollRef.current
        if (!scrollElement) {
            return
        }
        scrollElement.scrollTop = scrollElement.scrollHeight
    }, [messageFingerprint, isReplying])

    const submitReply = useCallback((): void => {
        if (!canSubmit) {
            return
        }

        onReply(replyText)
        setReply('')
        setIsReplying(false)
    }, [canSubmit, onReply, replyText])

    return (
        <div className="MarkdownNotebook__ai-chat" ref={scrollRef}>
            <div className="MarkdownNotebook__ai-chat-messages">
                {messages.map((message, index) => (
                    <NotebookAIChatMessageView
                        key={`${message.role}-${message.id ?? index}`}
                        message={message}
                        fallbackId={`notebook-ai-chat-message-${index}`}
                    />
                ))}
            </div>
            <div className="MarkdownNotebook__ai-chat-footer">
                <div className="MarkdownNotebook__ai-chat-footer-actions">
                    {canReply && !isReplying && onReply ? (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconMessage />}
                            onClick={() => setIsReplying(true)}
                        >
                            Reply
                        </LemonButton>
                    ) : null}
                    {canReply && !isReplying && onDismiss ? (
                        <LemonButton size="xsmall" type="secondary" onClick={onDismiss}>
                            Dismiss
                        </LemonButton>
                    ) : null}
                    {showOlderMessages && onShowOlderMessages ? (
                        <LemonButton size="xsmall" type="secondary" onClick={onShowOlderMessages}>
                            Show older messages
                        </LemonButton>
                    ) : null}
                    {showCollapseOlderMessages && onCollapseOlderMessages ? (
                        <LemonButton size="xsmall" type="secondary" onClick={onCollapseOlderMessages}>
                            Collapse older messages
                        </LemonButton>
                    ) : null}
                </div>
                {canReply && isReplying && onReply ? (
                    <div className="MarkdownNotebook__ai-chat-reply">
                        <LemonTextArea
                            className="MarkdownNotebook__ai-chat-reply-input"
                            value={reply}
                            onChange={setReply}
                            onPressEnter={submitReply}
                            onBlur={() => {
                                if (!reply.trim()) {
                                    setIsReplying(false)
                                }
                            }}
                            placeholder="Reply..."
                            minRows={2}
                            maxRows={6}
                            autoFocus
                            stopPropagation
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconSend />}
                            onClick={submitReply}
                            disabledReason={canSubmit ? undefined : 'Write a reply first'}
                        >
                            Send
                        </LemonButton>
                    </div>
                ) : null}
            </div>
        </div>
    )
}

function NotebookAIChatMessageView({
    message,
    fallbackId,
}: {
    message: NotebookAIChatMessage
    fallbackId: string
}): JSX.Element {
    if (message.role === 'human') {
        return <div className="MarkdownNotebook__ai-chat-human-message">{message.content}</div>
    }
    if (message.role === 'thinking') {
        return <NotebookAIChatThinking message={message.content} />
    }
    if (message.role === 'error') {
        return <div className="MarkdownNotebook__ai-chat-error">{message.content}</div>
    }
    return <NotebookAIChatAnswer id={message.id ?? fallbackId} content={message.content} compact />
}

function getNotebookAIChatBaseMessages(cachedLastAnswer: string | null): NotebookAIChatMessage[] {
    if (cachedLastAnswer) {
        return [{ role: 'assistant', id: 'notebook-ai-chat-cached-answer', content: cachedLastAnswer }]
    }
    return []
}

function getNotebookAIChatThreadMessages(
    threadGrouped: ThreadMessage[],
    threadLoading: boolean
): NotebookAIChatMessage[] {
    const messages = threadGrouped.flatMap((message, index): NotebookAIChatMessage[] => {
        const id = getThreadMessageId(message, index)
        const content = getMessageContent(message)

        if (message.type === AssistantMessageType.Human && content.trim()) {
            return [{ role: 'human', id, content }]
        }
        if (message.type === AssistantMessageType.Failure || message.status === 'error') {
            return [{ role: 'error', id, content: content || 'PostHog AI could not finish this request.' }]
        }
        if (message.type === AssistantMessageType.Notebook && message.status === 'completed') {
            return [{ role: 'assistant', id, content: 'Updated the notebook.' }]
        }
        if (isCompletedNotebookArtifactMessage(message)) {
            return [{ role: 'assistant', id, content: 'Updated the notebook.' }]
        }
        if (message.type === AssistantMessageType.Assistant) {
            if (content.trim()) {
                return [{ role: 'assistant', id, content }]
            }

            const thinkingMessage = getThinkingMessage(message)
            if (thinkingMessage || message.status === 'loading') {
                return [{ role: 'thinking', id, content: thinkingMessage ?? 'Thinking ...' }]
            }
        }

        return []
    })
    const latestMessage = messages.at(-1)

    if (threadLoading && latestMessage?.role !== 'thinking') {
        const thinkingMessage = [...threadGrouped].reverse().map(getThinkingMessage).find(Boolean)
        messages.push({
            role: 'thinking',
            id: 'notebook-ai-chat-thinking',
            content: thinkingMessage ?? 'Thinking ...',
        })
    }

    return messages
}

function getLatestNotebookAIChatAnswer(messages: NotebookAIChatMessage[]): string | null {
    return [...messages].reverse().find((message) => message.role === 'assistant')?.content ?? null
}

function getThreadMessageId(message: ThreadMessage, index: number): string {
    return 'id' in message && typeof message.id === 'string' ? message.id : `notebook-ai-chat-message-${index}`
}

function getMessageContent(message: ThreadMessage): string {
    return 'content' in message && typeof message.content === 'string' ? message.content : ''
}

function getThinkingMessage(message: ThreadMessage): string | null {
    if (message.type !== AssistantMessageType.Assistant) {
        return null
    }

    const thinking = message.meta?.thinking?.find(isThinkingMetadataEntry)
    return thinking?.thinking ?? null
}

function isThinkingMetadataEntry(entry: unknown): entry is { type: 'thinking'; thinking: string } {
    if (!entry || typeof entry !== 'object') {
        return false
    }

    const metadataEntry = entry as { type?: unknown; thinking?: unknown }
    return metadataEntry.type === 'thinking' && typeof metadataEntry.thinking === 'string'
}

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
    const contentStyle: CSSProperties | undefined = options.resizeable
        ? { height: attributes.height ?? options.heightEstimate, minHeight: options.minHeight }
        : undefined

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
                        <div className="MarkdownNotebook__real-node-content" style={contentStyle}>
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
                value={title}
                onChange={(value) => updateProps({ title: value })}
                placeholder="Title"
                autoFocus
            />
            <LemonInput
                value={src}
                onChange={(value) => updateProps({ src: value })}
                placeholder="Enter URL or iframe URL"
            />
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

function getNodeAttributeProps(props: NotebookComponentProps): NotebookComponentProps {
    return Object.entries(props).reduce<NotebookComponentProps>((attributeProps, [key, value]) => {
        if (key !== 'view' && key !== 'edit' && key !== 'hideFilters' && key !== 'hideResults') {
            attributeProps[key] = value
        }
        return attributeProps
    }, {})
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
