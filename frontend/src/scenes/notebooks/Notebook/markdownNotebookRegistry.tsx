import '../Nodes/NotebookNodeCohort'
import '../Nodes/NotebookNodeDashboard'
import '../Nodes/NotebookNodeCustomerJourney/NotebookNodeCustomerJourney'
import '../Nodes/NotebookNodeSQLV2'
import '../Nodes/NotebookNodeDuckSQL'
import '../Nodes/NotebookNodeEarlyAccessFeature'
import '../Nodes/NotebookNodeEmbed'
import '../Nodes/NotebookNodeExperiment'
import '../Nodes/NotebookNodeErrorTrackingIssue'
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
import '../Nodes/NotebookNodePythonV2'
import '../Nodes/NotebookNodeQuery'
import '../Nodes/NotebookNodeRecording'
import '../Nodes/NotebookNodeRelatedGroups'
import '../Nodes/NotebookNodeSupportTickets'
import '../Nodes/NotebookNodeSurvey'
import '../Nodes/NotebookNodeAction'
import '../Nodes/NotebookNodeTaskCreate'
import '../Nodes/NotebookNodeUsageMetrics'
import '../Nodes/NotebookNodeZendeskTickets'
import '../Nodes/NotebookNodeWorkflow'

import clsx from 'clsx'
import { BindLogic, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import {
    type CSSProperties,
    type PointerEvent as ReactPointerEvent,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
} from 'react'

import { IconComment, IconImage } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTextArea, lemonToast } from '@posthog/lemon-ui'

import {
    COMMON_INSERT_COMMAND_CATEGORY,
    QUERY_SQL_INSERT_COMMAND_KEY,
    createMarkdownNotebookRegistry,
} from 'lib/components/MarkdownNotebook'
import { NotebookComponentToolbarExtrasContext } from 'lib/components/MarkdownNotebook/componentToolbarExtras'
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
import { getSerializableProps, isNotebookPropValue } from 'lib/components/MarkdownNotebook/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { type FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { NODE_ICONS } from '../nodeIcons'
import { NotebookCodeCellRunButton } from '../Nodes/components/NotebookCodeCellRunButton'
import { NotebookNodeContext } from '../Nodes/NotebookNodeContext'
import { notebookNodeLogic } from '../Nodes/notebookNodeLogic'
import { getNotebookWidgetViewMenuItem } from '../notebookWidgetMenu'
import { CreatePostHogWidgetNodeOptions, NotebookNodeAttributes, NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import { NotebookDiscussionComment, getNotebookDiscussionCommentTitle } from './MarkdownNotebookDiscussionComment'
import { MarkdownNotebookNodeAttributeInput } from './MarkdownNotebookNodeAttributeInput'
import { getSqlV2PropsFromQueryProp } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

const INTERNAL_MARKDOWN_NODE_ATTRIBUTE_KEYS = new Set([
    'height',
    'nodeId',
    '__init',
    'children',
    'tabId',
    'placement',
    'view',
])

const NUMERIC_MARKDOWN_NODE_ATTRIBUTE_KEYS: Partial<Record<NotebookNodeType, string[]>> = {
    [NotebookNodeType.Cohort]: ['id'],
    [NotebookNodeType.Experiment]: ['id'],
    [NotebookNodeType.Dashboard]: ['id'],
    [NotebookNodeType.Action]: ['id'],
    [NotebookNodeType.Group]: ['groupTypeIndex'],
}

const MARKDOWN_NODE_ATTRIBUTE_LABELS: Partial<Record<NotebookNodeType, Record<string, string>>> = {
    [NotebookNodeType.Cohort]: {
        id: 'Cohort ID',
    },
    [NotebookNodeType.Dashboard]: {
        id: 'Dashboard ID',
    },
    [NotebookNodeType.Action]: {
        id: 'Action ID',
    },
    [NotebookNodeType.EarlyAccessFeature]: {
        id: 'Early access feature ID',
    },
    [NotebookNodeType.Experiment]: {
        id: 'Experiment ID',
    },
    [NotebookNodeType.FeatureFlag]: {
        id: 'Feature flag ID or key',
    },
    [NotebookNodeType.FeatureFlagCodeExample]: {
        id: 'Feature flag ID or key',
    },
    [NotebookNodeType.Group]: {
        groupTypeIndex: 'Group type index',
        id: 'Group key',
    },
    [NotebookNodeType.Recording]: {
        id: 'Session recording ID',
    },
    [NotebookNodeType.RecordingPlaylist]: {
        id: 'Recording playlist ID',
    },
    [NotebookNodeType.ErrorTrackingIssue]: {
        id: 'Error tracking issue ID',
    },
    [NotebookNodeType.LLMTrace]: {
        id: 'LLM trace ID',
    },
    [NotebookNodeType.Workflow]: {
        id: 'Workflow ID',
    },
    [NotebookNodeType.Person]: {
        distinctId: 'Distinct ID',
        id: 'Person UUID',
    },
    [NotebookNodeType.Survey]: {
        id: 'Survey ID',
    },
    [NotebookNodeType.ZendeskTickets]: {
        groupKey: 'Group key',
        personId: 'Person UUID',
    },
}

export const MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE: Partial<Record<string, NotebookNodeType>> = {
    Query: NotebookNodeType.Query,
    Insight: NotebookNodeType.Query,
    Dashboard: NotebookNodeType.Dashboard,
    Action: NotebookNodeType.Action,
    Workflow: NotebookNodeType.Workflow,
    Python: NotebookNodeType.Python,
    PythonV2: NotebookNodeType.PythonV2,
    DuckSQL: NotebookNodeType.DuckSQL,
    HogQLSQL: NotebookNodeType.HogQLSQL,
    SQLV2: NotebookNodeType.SQLV2,
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
    ErrorTrackingIssue: NotebookNodeType.ErrorTrackingIssue,
    UsageMetrics: NotebookNodeType.UsageMetrics,
    ZendeskTickets: NotebookNodeType.ZendeskTickets,
    RelatedGroups: NotebookNodeType.RelatedGroups,
    CustomerJourney: NotebookNodeType.CustomerJourney,
    SupportTickets: NotebookNodeType.SupportTickets,
}

const INSIGHT_NOTEBOOK_NODE_OPTIONS: CreatePostHogWidgetNodeOptions<any> = {
    ...KNOWN_NODES[NotebookNodeType.Query],
    editableTitle: false,
}
const INLINE_QUERY_NOTEBOOK_NODE_OPTIONS: CreatePostHogWidgetNodeOptions<any> = {
    ...KNOWN_NODES[NotebookNodeType.Query],
    attributes: {
        query: KNOWN_NODES[NotebookNodeType.Query].attributes.query,
        isDefaultFilterApplied: KNOWN_NODES[NotebookNodeType.Query].attributes.isDefaultFilterApplied,
        showSettings: KNOWN_NODES[NotebookNodeType.Query].attributes.showSettings,
        outputTab: KNOWN_NODES[NotebookNodeType.Query].attributes.outputTab,
    },
    defaultView: undefined,
    views: undefined,
}

function getMarkdownNodeOptions(tagName: string): CreatePostHogWidgetNodeOptions<any> | null {
    const nodeType = MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[tagName]

    if (tagName === 'Insight') {
        return INSIGHT_NOTEBOOK_NODE_OPTIONS
    }
    if (tagName === 'Query') {
        return INLINE_QUERY_NOTEBOOK_NODE_OPTIONS
    }
    return nodeType ? KNOWN_NODES[nodeType] : null
}

// A code cell's `filters` panel is its code editor, and the shell leaves that panel closed
// unless the node carries `showFilters`. A cell the user just inserted holds no code and no
// result, so without this it renders as an empty box with nothing to type into.
const CODE_CELL_EDITOR_OPEN_PROPS: NotebookComponentProps = { showFilters: true }

export const MARKDOWN_NODE_DEFINITIONS: {
    tagName: string
    category: string
    label?: string
    EditComponent?: NotebookComponentDefinition['EditComponent']
    ToolbarComponent?: NotebookComponentDefinition['ToolbarComponent']
    exclusiveEditPanel?: boolean
    insertCommand?: NotebookComponentDefinition['insertCommand']
}[] = [
    { tagName: 'Query', category: 'Insight' },
    { tagName: 'Insight', category: 'Insight', label: 'Insight' },
    { tagName: 'Dashboard', category: 'Insight' },
    { tagName: 'Action', category: 'Data' },
    { tagName: 'Workflow', category: 'PostHog' },
    // Legacy in-browser-kernel Python cell: still renders where it exists, but new cells
    // are always the revamped PythonV2 below, so it has no insertCommand.
    { tagName: 'Python', category: 'Code' },
    // The revamped (sandbox-kernel) Python cell; insertion gated like SQLV2 in
    // getMarkdownRegistryForFeatureFlags.
    {
        tagName: 'PythonV2',
        category: 'Code',
        label: 'Python',
        ToolbarComponent: NotebookCodeCellRunButton,
        insertCommand: {
            aliases: ['python', 'py'],
            defaultProps: () => ({
                ...getDefaultPropsForNodeType(NotebookNodeType.PythonV2),
                ...CODE_CELL_EDITOR_OPEN_PROPS,
                nodeId: uuid(),
            }),
        },
    },
    { tagName: 'DuckSQL', category: 'SQL', label: 'SQL (DuckDB)' },
    { tagName: 'HogQLSQL', category: 'SQL', label: 'SQL (HogQL)' },
    // insertCommand makes it show in the markdown insert menu; the feature-flag gate in
    // getMarkdownRegistryForFeatureFlags strips it when revamped-py-notebooks is off.
    {
        tagName: 'SQLV2',
        category: 'SQL',
        // The single SQL node once the legacy SQL cells are deprecated (they render but
        // are not insertable), so it reads as plain "SQL" in the insert menu.
        label: 'SQL',
        ToolbarComponent: NotebookCodeCellRunButton,
        insertCommand: {
            // Sits in the menu's top group, where the built-in SQL command it replaces used to be,
            // so SQL stays where people already reach for it. Only the menu grouping moves; the
            // definition's category still drives the node's SQL styling in the editor.
            category: COMMON_INSERT_COMMAND_CATEGORY,
            aliases: ['data', 'sql'],
            // New cells get a durable nodeId up front: parsed markdown block ids are content
            // fingerprints, so without a persisted id every prop change (running the cell
            // writes runId/result) would orphan the cell's run history and cross-cell refs.
            defaultProps: () => ({
                ...getDefaultPropsForNodeType(NotebookNodeType.SQLV2),
                ...CODE_CELL_EDITOR_OPEN_PROPS,
                nodeId: uuid(),
            }),
        },
    },
    { tagName: 'RecordingPlaylist', category: 'Data', label: 'Session recordings' },
    { tagName: 'Experiment', category: 'Experiment' },
    { tagName: 'Image', category: 'Media', EditComponent: ImageEdit },
    { tagName: 'Embed', category: 'Media', EditComponent: EmbedEdit },
    { tagName: 'Latex', category: 'Media', label: 'LaTeX', EditComponent: LatexEdit },
    { tagName: 'FeatureFlag', category: 'PostHog', label: 'Feature flag' },
    { tagName: 'Survey', category: 'PostHog' },
    { tagName: 'Person', category: 'Data' },
    { tagName: 'Group', category: 'Data' },
    { tagName: 'Cohort', category: 'Data' },
    { tagName: 'Map', category: 'Data' },
    { tagName: 'Recording', category: 'Data' },
    { tagName: 'Backlink', category: 'PostHog' },
    { tagName: 'ReplayTimestamp', category: 'PostHog' },
    { tagName: 'PersonFeed', category: 'Data' },
    { tagName: 'PersonProperties', category: 'Data' },
    { tagName: 'GroupProperties', category: 'Data' },
    { tagName: 'TaskCreate', category: 'PostHog' },
    { tagName: 'LLMTrace', category: 'PostHog' },
    { tagName: 'Issues', category: 'PostHog' },
    { tagName: 'ErrorTrackingIssue', category: 'PostHog', label: 'Error tracking issue' },
    { tagName: 'UsageMetrics', category: 'PostHog' },
    { tagName: 'ZendeskTickets', category: 'PostHog' },
    { tagName: 'RelatedGroups', category: 'PostHog' },
    { tagName: 'CustomerJourney', category: 'PostHog' },
    { tagName: 'SupportTickets', category: 'PostHog' },
    { tagName: 'EarlyAccessFeature', category: 'PostHog', label: 'Early access feature' },
    {
        tagName: 'FeatureFlagCodeExample',
        category: 'PostHog',
        label: 'Feature flag code example',
    },
]

export const NOTEBOOK_MARKDOWN_REGISTRY: NotebookComponentRegistry = createMarkdownNotebookRegistry([
    ...MARKDOWN_NODE_DEFINITIONS.map((definition) => {
        const nodeType = MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[definition.tagName]
        const options = getMarkdownNodeOptions(definition.tagName)
        const label = definition.label ?? options?.titlePlaceholder ?? splitTagName(definition.tagName)

        return {
            tagName: definition.tagName,
            label,
            category: definition.category,
            icon: nodeType ? NODE_ICONS[nodeType] : undefined,
            defaultProps: () => getDefaultPropsForNodeType(nodeType),
            ViewComponent: RealNotebookNodeView,
            EditComponent: definition.EditComponent ?? RealNotebookNodeEdit,
            ToolbarComponent: definition.ToolbarComponent,
            exclusiveEditPanel: definition.exclusiveEditPanel,
            editableTitle: options?.editableTitle,
            // Nodes with a Settings panel keep their filters toggle on read-only canvases
            // (customer profiles), where the panel is the only way to configure them.
            viewModeFilters: !!options?.Settings,
            insertCommand: definition.insertCommand,
            getTitle: (node: NotebookComponentBlockNode) =>
                getMarkdownNotebookNodeTitle(node, nodeType, options, label),
            getHref: (node: NotebookComponentBlockNode) => getMarkdownNotebookNodeHref(node, nodeType, options),
        }
    }),
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

// Node tags that only appear in the markdown insert menu when their feature flag is on.
// Only insertion is gated — rendering of already-inserted nodes is never gated.
export function getMarkdownRegistryForFeatureFlags(featureFlags: FeatureFlagsSet): NotebookComponentRegistry {
    const hiddenTags: string[] = []
    if (!featureFlags[FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS]) {
        hiddenTags.push('SQLV2', 'PythonV2')
    }

    if (hiddenTags.length === 0) {
        return NOTEBOOK_MARKDOWN_REGISTRY
    }

    // Dropping insertCommand hides the node from the insert menu (it filters falsy
    // insertCommand), while the ViewComponent stays so existing nodes still render.
    const components = { ...NOTEBOOK_MARKDOWN_REGISTRY.components }
    for (const tagName of hiddenTags) {
        const definition = components[tagName]
        if (definition) {
            components[tagName] = { ...definition, insertCommand: undefined }
        }
    }
    return { components }
}

// The editor's built-in insert commands live outside the registry, so hiding a node's tag is not
// enough to keep it out of the menu: a built-in that inserts the same tag has to be dropped by key.
export function getHiddenInsertCommandKeysForFeatureFlags(featureFlags: FeatureFlagsSet): string[] {
    // The built-in SQL command inserts a legacy `<Query>` HogQL cell, which SQLV2 replaces: it runs
    // through the sandbox, names a dataframe other cells can reference, and keeps run history.
    // Offering both would put two entries labeled "SQL" in the menu.
    return featureFlags[FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS] ? [QUERY_SQL_INSERT_COMMAND_KEY] : []
}

export function getMarkdownNotebookNodeTitle(
    node: NotebookComponentBlockNode,
    nodeType: NotebookNodeType | undefined,
    options: CreatePostHogWidgetNodeOptions<any> | null,
    fallback: string
): string | null {
    const attributes = getNodeAttributes(node.props, node.id, options, nodeType, false)
    const explicitTitle = getUnknownStringProp(attributes.title)

    if (explicitTitle && options?.editableTitle !== false) {
        return explicitTitle
    }

    if (nodeType === NotebookNodeType.Query) {
        if (attributes.id) {
            return fallback
        }
        // No fallback label: an unnamed/SQL query stays empty so the title field reads as "Add a title"
        return getQueryTitle(attributes.query)
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
        nodeType === NotebookNodeType.PythonV2 ||
        nodeType === NotebookNodeType.SQLV2 ||
        nodeType === NotebookNodeType.DuckSQL ||
        nodeType === NotebookNodeType.HogQLSQL
    ) {
        // Never suggest the code/SQL body itself as a title — fall back to the language label
        return fallback
    }

    return (
        summarizeTitle(options?.serializedText?.(attributes)) ??
        getUnknownStringProp(attributes.name) ??
        getUnknownStringProp(attributes.id) ??
        fallback
    )
}

export function getMarkdownNotebookNodeHref(
    node: NotebookComponentBlockNode,
    nodeType: NotebookNodeType | undefined,
    options: CreatePostHogWidgetNodeOptions<any> | null
): string | null {
    // Reuse the legacy node's `href` (e.g. Query → urls.insightView/urls.insightNew) so saved and
    // ad-hoc insights, recordings, persons, etc. all expose a link to the underlying resource.
    if (!options?.href) {
        return null
    }
    const attributes = getNodeAttributes(node.props, node.id, options, nodeType, false)
    const href = typeof options.href === 'function' ? options.href(attributes) : options.href
    return href ?? null
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
        // Leave SQL queries untitled initially — never suggest the SQL body or a generic label
        return null
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
    if (sourceKind === 'ActorsQuery') {
        return 'People'
    }

    // Don't suggest raw schema kinds (e.g. "DataTableNode") as a title
    return null
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
    const notebookNodeType = MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[props.node.tagName]
    const options = getMarkdownNodeOptions(props.node.tagName)

    if (!options || !notebookNodeType) {
        return <div className="MarkdownNotebook__component-preview">Unsupported notebook node.</div>
    }

    if (!options.Settings) {
        return <RealNotebookNodeAttributeEdit {...props} notebookNodeType={notebookNodeType} options={options} />
    }

    return (
        <>
            <RealNotebookNodeIdentityAndViewEdit {...props} notebookNodeType={notebookNodeType} options={options} />
            <RealNotebookNodeComponent {...props} forceEditing editOnly />
        </>
    )
}

export function RealNotebookNodeIdentityAndViewEdit({
    node,
    updateProps,
    notebookNodeType,
    options,
}: NotebookComponentRenderProps & {
    notebookNodeType: NotebookNodeType
    options: CreatePostHogWidgetNodeOptions<any>
}): JSX.Element | null {
    const hasId = 'id' in options.attributes
    if (!hasId && !options.views) {
        return null
    }

    const attributes = getNodeAttributes(node.props, node.id, options, notebookNodeType, true)

    return (
        <div className="MarkdownNotebook__component-form">
            {hasId ? (
                <RealNotebookNodeAttributeField
                    node={node}
                    updateProps={updateProps}
                    notebookNodeType={notebookNodeType}
                    attributeKey="id"
                    value={attributes.id}
                    autoFocus={wasNotebookNodeJustInserted(node.id)}
                />
            ) : null}
            {options.views ? (
                <RealNotebookNodeViewSelect node={node} updateProps={updateProps} options={options} />
            ) : null}
        </div>
    )
}

function RealNotebookNodeViewSelect({
    node,
    updateProps,
    options,
}: Pick<NotebookComponentRenderProps, 'node' | 'updateProps'> & {
    options: CreatePostHogWidgetNodeOptions<any>
}): JSX.Element {
    const defaultViewKey = options.defaultView?.key ?? ''
    const widgetView =
        typeof node.props.view === 'string' && (node.props.view === defaultViewKey || options.views?.[node.props.view])
            ? node.props.view
            : defaultViewKey

    return (
        <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-secondary">View</span>
            <LemonSelect
                aria-label="View"
                fullWidth
                value={widgetView}
                onChange={(view) => updateProps({ view: view === defaultViewKey ? undefined : view })}
                options={[
                    {
                        value: defaultViewKey,
                        label: options.defaultView?.label ?? 'Default',
                        tooltip: options.defaultView?.description,
                    },
                    ...Object.entries(options.views ?? {}).map(([value, view]) => ({
                        value,
                        label: view.label,
                        tooltip: view.description,
                    })),
                ]}
            />
        </label>
    )
}

function RealNotebookNodeAttributeField({
    node,
    updateProps,
    notebookNodeType,
    attributeKey,
    value,
    autoFocus,
}: Pick<NotebookComponentRenderProps, 'node' | 'updateProps'> & {
    notebookNodeType: NotebookNodeType
    attributeKey: string
    value: NotebookPropValue | undefined
    autoFocus: boolean
}): JSX.Element {
    const label = getMarkdownNodeAttributeLabel(notebookNodeType, attributeKey)

    return (
        <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-secondary">{label}</span>
            <MarkdownNotebookNodeAttributeInput
                attributeKey={attributeKey}
                label={label}
                tagName={node.tagName}
                value={getPrimitiveNotebookPropInputValue(value)}
                onTextChange={(nextValue) =>
                    updateProps({
                        [attributeKey]: getSerializableAttributeInputValue(notebookNodeType, attributeKey, nextValue),
                    })
                }
                onEntitySelect={(nextValue) => updateProps({ [attributeKey]: nextValue })}
                autoFocus={autoFocus}
            />
        </label>
    )
}

export function RealNotebookNodeAttributeEdit({
    node,
    updateProps,
    notebookNodeType,
    options,
}: NotebookComponentRenderProps & {
    notebookNodeType: NotebookNodeType
    options: CreatePostHogWidgetNodeOptions<any>
}): JSX.Element {
    const attributes = getNodeAttributes(node.props, node.id, options, notebookNodeType, true)
    const attributeKeys = getEditableNodeAttributeKeys(options, attributes)
    const idAttributeKey = attributeKeys.find((key) => key === 'id')
    const remainingAttributeKeys = attributeKeys.filter((key) => key !== idAttributeKey)
    const shouldAutoFocus = wasNotebookNodeJustInserted(node.id)

    if (!attributeKeys.length && !options.views) {
        return (
            <div className="MarkdownNotebook__component-form text-secondary text-sm">
                No editable filters for this block.
            </div>
        )
    }

    return (
        <div className="MarkdownNotebook__component-form">
            {idAttributeKey ? (
                <RealNotebookNodeAttributeField
                    node={node}
                    updateProps={updateProps}
                    notebookNodeType={notebookNodeType}
                    attributeKey={idAttributeKey}
                    value={attributes[idAttributeKey]}
                    autoFocus={shouldAutoFocus}
                />
            ) : null}
            {options.views ? (
                <RealNotebookNodeViewSelect node={node} updateProps={updateProps} options={options} />
            ) : null}
            {remainingAttributeKeys.map((key, index) => (
                <RealNotebookNodeAttributeField
                    key={key}
                    node={node}
                    updateProps={updateProps}
                    notebookNodeType={notebookNodeType}
                    attributeKey={key}
                    value={attributes[key]}
                    autoFocus={!idAttributeKey && index === 0 && shouldAutoFocus}
                />
            ))}
        </div>
    )
}

export function RealNotebookNodeComponent({
    node,
    mode,
    notebookMode,
    updateProps,
    deleteNode,
    forceEditing = false,
    editOnly = false,
}: NotebookComponentRenderProps & { forceEditing?: boolean; editOnly?: boolean }): JSX.Element {
    const notebookNodeType = MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[node.tagName]
    const options = getMarkdownNodeOptions(node.tagName)

    if (!options || !notebookNodeType) {
        return <div className="MarkdownNotebook__component-preview">Unsupported notebook node.</div>
    }

    return (
        <MountedRealNotebookNodeComponent
            node={node}
            mode={mode}
            notebookMode={notebookMode}
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
            editableTitle: options.editableTitle,
            settingsPlacement: options.settingsPlacement,
        }),
        [attributes, mountedNotebookLogic, notebookNodeType, options, updateAttributes]
    )

    const nodeLogic = useMountedLogic(notebookNodeLogic(logicProps))
    const {
        actions: nodeActions,
        customMenuItems: nodeMenuItems,
        settingsDisabledReason: nodeSettingsDisabledReason,
        title: nodeTitle,
        titleStatus: nodeTitleStatus,
    } = useValues(nodeLogic)
    const setToolbarExtras = useContext(NotebookComponentToolbarExtrasContext)
    const viewMenuItem = useMemo(
        () => getNotebookWidgetViewMenuItem(options, attributes, updateAttributes),
        [attributes, options, updateAttributes]
    )
    const toolbarExtras = useMemo(
        () => ({
            actions: nodeActions,
            menuItems: nodeMenuItems,
            editMenuItems: viewMenuItem ? [viewMenuItem] : null,
            filtersDisabledReason: nodeSettingsDisabledReason,
            title: nodeTitle,
            titleStatus: nodeTitleStatus,
        }),
        [nodeActions, nodeMenuItems, nodeSettingsDisabledReason, nodeTitle, nodeTitleStatus, viewMenuItem]
    )

    // The settings-panel instance (editOnly) shares the shell with the content instance;
    // only the latter publishes, so a hidden panel doesn't clear the other's extras.
    // No unmount cleanup on purpose: collapsing the node unmounts the component, and the
    // toolbar menu must survive the collapse. The shell drops the state when IT unmounts.
    useEffect(() => {
        if (editOnly || !setToolbarExtras) {
            return
        }
        setToolbarExtras(toolbarExtras)
    }, [editOnly, setToolbarExtras, toolbarExtras])

    const Component = options.Component
    const Settings = options.Settings
    const showSettings = forceEditing && Settings
    const showContent = !editOnly
    const isNotebookEditable = (notebookMode ?? mode) === 'edit'
    const isResizeable =
        isNotebookEditable &&
        (typeof options.resizeable === 'function' ? options.resizeable(attributes) : (options.resizeable ?? true))
    const contentStyle: CSSProperties | undefined =
        isResizeable || attributes.height
            ? { height: attributes.height ?? options.heightEstimate, minHeight: options.minHeight }
            : undefined
    // Nodes that declare their own minHeight (e.g. LaTeX) size to their content instead of the 8rem default
    const nodeStyle: CSSProperties | undefined =
        options.minHeight !== undefined
            ? ({
                  '--markdown-notebook-real-node-min-height':
                      typeof options.minHeight === 'number' ? `${options.minHeight}px` : options.minHeight,
              } as CSSProperties)
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
                <div
                    className={clsx(
                        'MarkdownNotebook__real-node',
                        // The settings-only (filters panel) instance sizes to its content — the
                        // 8rem min-height is for node output, not a one-row filter bar.
                        editOnly && 'MarkdownNotebook__real-node--settings-only'
                    )}
                    style={nodeStyle}
                >
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
    const formRef = useRef<HTMLDivElement | null>(null)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            updateProps({ src: url, ...(alt ? {} : { alt: fileName }) })
            posthog.capture('notebook image uploaded', { name: fileName })
        },
        onError: (detail) => {
            posthog.capture('notebook image upload failed', { error: detail })
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    return (
        <div className="MarkdownNotebook__component-form" ref={formRef}>
            <LemonFileInput
                accept="image/*"
                multiple={false}
                value={filesToUpload}
                onChange={setFilesToUpload}
                loading={uploading}
                showUploadedFiles={false}
                alternativeDropTargetRef={formRef}
                callToAction={
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={uploading ? <Spinner className="text-lg" textColored /> : <IconImage />}
                        disabledReason={objectStorageAvailable ? undefined : 'Enable object storage to upload images'}
                        tooltip={objectStorageAvailable ? 'Click here or drag and drop to upload an image' : null}
                    >
                        Upload image
                    </LemonButton>
                }
            />
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
        ...(nodeType === NotebookNodeType.SQLV2 ? getSqlV2PropsFromQueryProp(props) : null),
        nodeId: typeof props.nodeId === 'string' ? props.nodeId : fallbackNodeId,
    } as NotebookNodeAttributes<any>

    if (nodeType === NotebookNodeType.Latex && !forceEditing) {
        attributes.editing = false
    }

    return attributes
}

export function getNodeAttributeProps(props: NotebookComponentProps): NotebookComponentProps {
    return Object.entries(props).reduce<NotebookComponentProps>((attributeProps, [key, value]) => {
        if (
            (key !== 'view' || typeof value !== 'boolean') &&
            key !== 'edit' &&
            key !== 'hideFilters' &&
            key !== 'hideResults' &&
            key !== 'showFilters' &&
            key !== 'showResults'
        ) {
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

export function getEditableNodeAttributeKeys(
    options: CreatePostHogWidgetNodeOptions<any>,
    attributes: Partial<NotebookNodeAttributes<any>>
): string[] {
    return Object.keys(options.attributes).filter((key) => {
        if (INTERNAL_MARKDOWN_NODE_ATTRIBUTE_KEYS.has(key)) {
            return false
        }

        const value = attributes[key]
        return value === undefined || value === null || ['boolean', 'number', 'string'].includes(typeof value)
    })
}

export function getMarkdownNodeAttributeLabel(notebookNodeType: NotebookNodeType, key: string): string {
    return MARKDOWN_NODE_ATTRIBUTE_LABELS[notebookNodeType]?.[key] ?? splitTagName(key)
}

export function getPrimitiveNotebookPropInputValue(value: NotebookPropValue | undefined): string {
    if (value === undefined || value === null) {
        return ''
    }
    return typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string' ? String(value) : ''
}

export function getSerializableAttributeInputValue(
    notebookNodeType: NotebookNodeType,
    key: string,
    value: string
): NotebookPropValue | undefined {
    const trimmedValue = value.trim()
    if (!trimmedValue) {
        return undefined
    }

    if (NUMERIC_MARKDOWN_NODE_ATTRIBUTE_KEYS[notebookNodeType]?.includes(key)) {
        const numericValue = Number(trimmedValue)
        return Number.isFinite(numericValue) ? numericValue : trimmedValue
    }

    return trimmedValue
}

export function splitTagName(tagName: string): string {
    return tagName.replace(/([a-z])([A-Z])/g, '$1 $2')
}
