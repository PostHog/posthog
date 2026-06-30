import { useState } from 'react'

import {
    IconCode,
    IconComment,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconMap,
    IconMinus,
    IconPeople,
    IconPencil,
    IconRewindPlay,
    IconUpload,
} from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from './freshlyInserted'
import {
    NotebookComponentDefinition,
    NotebookComponentBlockNode,
    NotebookComponentProps,
    NotebookComponentRegistry,
    NotebookComponentRenderProps,
    NotebookPropValue,
} from './types'
import { isNotebookComponentProps } from './utils'

export function createMarkdownNotebookRegistry(definitions: NotebookComponentDefinition[]): NotebookComponentRegistry {
    return {
        components: definitions.reduce<Record<string, NotebookComponentDefinition>>((accumulator, definition) => {
            accumulator[definition.tagName] = definition
            return accumulator
        }, {}),
    }
}

export function mergeMarkdownNotebookRegistries(
    baseRegistry: NotebookComponentRegistry,
    overrideRegistry?: NotebookComponentRegistry
): NotebookComponentRegistry {
    return {
        components: {
            ...baseRegistry.components,
            ...overrideRegistry?.components,
        },
    }
}

export function getMarkdownNotebookComponentDefinition(
    registry: NotebookComponentRegistry,
    tagName: string
): NotebookComponentDefinition | null {
    return registry.components[tagName] ?? null
}

export function getMarkdownNotebookComponentDefaultProps(
    definition: NotebookComponentDefinition
): NotebookComponentProps {
    return typeof definition.defaultProps === 'function' ? definition.defaultProps() : (definition.defaultProps ?? {})
}

export function getMarkdownNotebookDefaultRegistry(): NotebookComponentRegistry {
    return createMarkdownNotebookRegistry([
        makeQueryDefinition(),
        makeDefinition({
            tagName: 'Image',
            label: 'Image',
            category: 'Media',
            description: 'Image block',
            icon: <IconUpload />,
            defaultProps: { src: '', alt: '' },
            getTitle: getImageComponentTitle,
            ViewComponent: ImageView,
            EditComponent: ImageEdit,
        }),
        makeDefinition({
            tagName: 'Divider',
            label: 'Divider',
            category: 'Text',
            description: 'Horizontal rule',
            aliases: ['hr', 'horizontal rule', 'separator', 'line'],
            icon: <IconMinus />,
            defaultProps: {},
            getTitle: () => null,
            hideModeActions: true,
            ViewComponent: DividerView,
            insertCommand: {},
        }),
        makeDefinition({
            tagName: 'Comment',
            label: 'Comment',
            category: 'Text',
            description: 'Inline note, stored as a markdown comment',
            aliases: ['note', 'annotation', 'todo'],
            icon: <IconComment />,
            defaultProps: { text: '' },
            getTitle: (node) => summarizeText(getStringProp(node.props.text)),
            hideModeActions: true,
            ViewComponent: CommentView,
            insertCommand: {},
        }),
        makeDefinition({
            tagName: 'Embed',
            label: 'Embed',
            category: 'Media',
            description: 'Embedded external content',
            icon: <IconCode />,
            defaultProps: { src: '', title: 'Embedded content' },
            getTitle: getEmbedComponentTitle,
            ViewComponent: EmbedView,
            EditComponent: EmbedEdit,
        }),
        makeDefinition({
            tagName: 'Latex',
            label: 'LaTeX',
            category: 'Media',
            description: 'Math expression',
            icon: <IconCode />,
            defaultProps: { content: 'E=mc^2' },
            getTitle: (node) => getStringProp(node.props.title) ?? summarizeText(getStringProp(node.props.content)),
            ViewComponent: LatexView,
            EditComponent: LatexEdit,
        }),
        makeDefinition({
            tagName: 'Python',
            label: 'Python',
            category: 'Code',
            description: 'Python analysis block',
            icon: <IconCode />,
            defaultProps: { code: '', title: 'Python' },
            getTitle: (node) => getCodeComponentTitle(node, 'Python'),
            ViewComponent: CodeView,
        }),
        makeDefinition({
            tagName: 'DuckSQL',
            label: 'SQL (DuckDB)',
            category: 'Code',
            description: 'DuckDB SQL block',
            icon: <IconDatabase />,
            defaultProps: { code: '', returnVariable: 'duck_df', title: 'SQL (DuckDB)' },
            getTitle: (node) => getCodeComponentTitle(node, 'SQL (DuckDB)'),
            ViewComponent: CodeView,
        }),
        makeDefinition({
            tagName: 'HogQLSQL',
            label: 'SQL (HogQL)',
            category: 'Code',
            description: 'HogQL SQL block',
            icon: <IconDatabase />,
            defaultProps: { code: '', returnVariable: 'hogql_df', title: 'SQL (HogQL)' },
            getTitle: (node) => getCodeComponentTitle(node, 'SQL (HogQL)'),
            ViewComponent: CodeView,
        }),
        makeDefinition({
            tagName: 'RecordingPlaylist',
            label: 'Session recordings',
            category: 'Data',
            description: 'Session replay playlist',
            icon: <IconRewindPlay />,
            defaultProps: { title: 'Session recordings' },
            ViewComponent: SummaryView,
        }),
        makeDefinition({
            tagName: 'FeatureFlag',
            label: 'Feature flag',
            category: 'PostHog',
            icon: <IconFlag />,
            defaultProps: { id: '' },
            ViewComponent: SummaryView,
        }),
        makeDefinition({
            tagName: 'Experiment',
            label: 'Experiment',
            category: 'PostHog',
            icon: <IconFlask />,
            defaultProps: { id: '' },
            ViewComponent: SummaryView,
        }),
        makeDefinition({
            tagName: 'Survey',
            label: 'Survey',
            category: 'PostHog',
            defaultProps: { id: '' },
            ViewComponent: SummaryView,
        }),
        makeDefinition({
            tagName: 'Person',
            label: 'Person',
            category: 'Data',
            icon: <IconPeople />,
            defaultProps: { id: '' },
            ViewComponent: SummaryView,
        }),
        makeDefinition({
            tagName: 'Group',
            label: 'Group',
            category: 'Data',
            icon: <IconPeople />,
            defaultProps: { type: '', key: '' },
            ViewComponent: SummaryView,
        }),
        makeDefinition({
            tagName: 'Cohort',
            label: 'Cohort',
            category: 'Data',
            icon: <IconPeople />,
            defaultProps: { id: '' },
            ViewComponent: SummaryView,
        }),
        makeDefinition({
            tagName: 'Map',
            label: 'Map',
            category: 'Data',
            icon: <IconMap />,
            defaultProps: { title: 'Map' },
            ViewComponent: SummaryView,
        }),
        ...[
            'Backlink',
            'ReplayTimestamp',
            'PersonFeed',
            'PersonProperties',
            'GroupProperties',
            'TaskCreate',
            'LLMTrace',
            'Issues',
            'UsageMetrics',
            'ZendeskTickets',
            'RelatedGroups',
            'CustomerJourney',
            'SupportTickets',
            'EarlyAccessFeature',
            'FeatureFlagCodeExample',
            'Recording',
        ].map((tagName) =>
            makeDefinition({
                tagName,
                label: splitTagName(tagName),
                category: 'PostHog',
                defaultProps: { title: splitTagName(tagName) },
                ViewComponent: SummaryView,
            })
        ),
    ])
}

function makeQueryDefinition(): NotebookComponentDefinition {
    return makeDefinition({
        tagName: 'Query',
        label: 'Query',
        category: 'Insight',
        description: 'Insight or query-backed block',
        icon: <IconGraph />,
        getTitle: getQueryComponentTitle,
        defaultProps: {
            query: {
                kind: 'DataTableNode',
                source: {
                    kind: 'EventsQuery',
                    select: ['*', 'event', 'person', 'timestamp'],
                    after: '-24h',
                    limit: 100,
                },
            },
        },
        validateProps: (props) => {
            const query = props.query
            if (!query || typeof query !== 'object' || Array.isArray(query)) {
                return ['Query requires a query object']
            }
            if (!('kind' in query)) {
                return ['Query object requires a kind field']
            }
            return []
        },
        ViewComponent: QueryView,
    })
}

function makeDefinition(
    definition: Omit<NotebookComponentDefinition, 'EditComponent'> & {
        EditComponent?: NotebookComponentDefinition['EditComponent']
    }
): NotebookComponentDefinition {
    return {
        EditComponent: GenericComponentEdit,
        getTitle: getDefaultComponentTitle,
        ...definition,
    }
}

function QueryView({ node }: NotebookComponentRenderProps): JSX.Element {
    const query = node.props.query

    return (
        <div className="MarkdownNotebook__component-preview">
            <pre>{JSON.stringify(query, null, 2)}</pre>
        </div>
    )
}

function DividerView(_: NotebookComponentRenderProps): JSX.Element {
    return <hr className="MarkdownNotebook__divider" />
}

// Comment nodes render through CommentBlock in renderNode; this is the registry fallback.
function CommentView({ node }: NotebookComponentRenderProps): JSX.Element {
    const text = typeof node.props.text === 'string' ? node.props.text : ''
    return <div className="MarkdownNotebook__comment-chip">{text || 'Comment'}</div>
}

function ImageView({ node }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const alt = typeof node.props.alt === 'string' ? node.props.alt : ''

    return src ? (
        <img className="MarkdownNotebook__image" src={src} alt={alt} />
    ) : (
        <SummaryView node={node} mode="view" updateProps={() => {}} deleteNode={() => {}} />
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
                autoFocus={wasNotebookNodeJustInserted(node.id)}
            />
            <LemonInput value={alt} onChange={(value) => updateProps({ alt: value })} placeholder="Alt text" />
        </div>
    )
}

function EmbedView({ node }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const title = typeof node.props.title === 'string' ? node.props.title : 'Embedded content'

    return src ? (
        <iframe className="MarkdownNotebook__embed" src={src} title={title} sandbox="allow-scripts allow-same-origin" />
    ) : (
        <SummaryView node={node} mode="view" updateProps={() => {}} deleteNode={() => {}} />
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
                autoFocus={wasNotebookNodeJustInserted(node.id)}
            />
            <LemonInput
                value={src}
                onChange={(value) => updateProps({ src: value })}
                placeholder="https://example.com/embed"
            />
        </div>
    )
}

function LatexView({ node }: NotebookComponentRenderProps): JSX.Element {
    const content = typeof node.props.content === 'string' ? node.props.content : ''
    return <div className="MarkdownNotebook__latex">{content}</div>
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
                autoFocus={wasNotebookNodeJustInserted(node.id)}
            />
        </div>
    )
}

function CodeView({ node }: NotebookComponentRenderProps): JSX.Element {
    const code = typeof node.props.code === 'string' ? node.props.code : ''

    return (
        <div className="MarkdownNotebook__code-component">
            <pre>{code || 'No code yet'}</pre>
        </div>
    )
}

function SummaryView({ node }: NotebookComponentRenderProps): JSX.Element {
    return (
        <div className="MarkdownNotebook__component-preview">
            <pre>{JSON.stringify(node.props, null, 2)}</pre>
        </div>
    )
}

function getDefaultComponentTitle(node: NotebookComponentBlockNode): string | null {
    return (
        getStringProp(node.props.title) ??
        getStringProp(node.props.name) ??
        getStringProp(node.props.url) ??
        getStringProp(node.props.href) ??
        getStringProp(node.props.src) ??
        getStringProp(node.props.id)
    )
}

function getImageComponentTitle(node: NotebookComponentBlockNode): string | null {
    return (
        getStringProp(node.props.title) ??
        getStringProp(node.props.alt) ??
        getStringProp(node.props.src) ??
        getDefaultComponentTitle(node)
    )
}

function getEmbedComponentTitle(node: NotebookComponentBlockNode): string | null {
    return getStringProp(node.props.title) ?? getStringProp(node.props.src) ?? getDefaultComponentTitle(node)
}

function getCodeComponentTitle(node: NotebookComponentBlockNode, fallback: string): string | null {
    // Never suggest the code/SQL body itself as a title — fall back to the language label
    return getStringProp(node.props.title) ?? fallback
}

function getQueryComponentTitle(node: NotebookComponentBlockNode): string | null {
    const explicitTitle = getStringProp(node.props.title)
    if (explicitTitle) {
        return explicitTitle
    }

    const query = getObjectProp(node.props.query)
    const source = getObjectProp(query?.source)
    const queryKind = getStringProp(query?.kind)
    const sourceKind = getStringProp(source?.kind)

    if (queryKind === 'SavedInsightNode') {
        return getStringProp(query?.name) ?? getStringProp(query?.shortId) ?? 'Saved insight'
    }
    if (sourceKind === 'HogQLQuery') {
        // Leave SQL queries untitled initially — never suggest the SQL body or a generic label
        return null
    }
    if (sourceKind === 'TrendsQuery') {
        return source ? (getSeriesSummary(source) ?? 'Trend') : 'Trend'
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
    return getDefaultComponentTitle(node)
}

function getSeriesSummary(query: Record<string, NotebookPropValue>): string | null {
    const series = query.series
    if (!Array.isArray(series)) {
        return null
    }

    const names = series
        .map((seriesItem) => (getObjectProp(seriesItem) ? getStringProp(getObjectProp(seriesItem)?.event) : null))
        .filter(Boolean)

    return names.length ? names.join(', ') : null
}

function getStringProp(value: NotebookPropValue | undefined): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

function getObjectProp(value: NotebookPropValue | undefined): Record<string, NotebookPropValue> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function summarizeText(value: string | null): string | null {
    const oneLineValue = value?.replace(/\s+/g, ' ').trim()
    if (!oneLineValue) {
        return null
    }
    return oneLineValue.length > 120 ? `${oneLineValue.slice(0, 117)}...` : oneLineValue
}

function GenericComponentEdit({ node, updateProps }: NotebookComponentRenderProps): JSX.Element {
    const [json, setJson] = useState(() => JSON.stringify(node.props, null, 2))
    const [error, setError] = useState<string | null>(null)

    const apply = (): void => {
        try {
            const parsed: unknown = JSON.parse(json)
            if (!isNotebookComponentProps(parsed)) {
                setError('Props must be a JSON object with serializable values.')
                return
            }
            updateProps(parsed)
            setError(null)
        } catch (error) {
            setError(error instanceof Error ? error.message : 'Invalid JSON')
        }
    }

    return (
        <div className="MarkdownNotebook__component-edit">
            <textarea
                aria-label={`${splitTagName(node.tagName)} props`}
                value={json}
                onChange={(event) => setJson(event.target.value)}
                spellCheck={false}
            />
            <div className="MarkdownNotebook__component-edit-footer">
                {error ? (
                    <span className="text-danger">{error}</span>
                ) : (
                    <span className="text-muted">Component props</span>
                )}
                <LemonButton size="small" icon={<IconPencil />} onClick={apply}>
                    Apply
                </LemonButton>
            </div>
        </div>
    )
}

function splitTagName(tagName: string): string {
    return tagName.replace(/([a-z])([A-Z])/g, '$1 $2')
}
