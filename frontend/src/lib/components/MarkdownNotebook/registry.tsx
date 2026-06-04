import { useState } from 'react'

import {
    IconCode,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconMap,
    IconPeople,
    IconPencil,
    IconRewindPlay,
    IconUpload,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NotebookComponentDefinition, NotebookComponentRegistry, NotebookComponentRenderProps } from './types'
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
            ViewComponent: ImageView,
        }),
        makeDefinition({
            tagName: 'Embed',
            label: 'Embed',
            category: 'Media',
            description: 'Embedded external content',
            icon: <IconCode />,
            defaultProps: { src: '', title: 'Embedded content' },
            ViewComponent: EmbedView,
        }),
        makeDefinition({
            tagName: 'Latex',
            label: 'LaTeX',
            category: 'Media',
            description: 'Math expression',
            icon: <IconCode />,
            defaultProps: { content: 'E=mc^2' },
            ViewComponent: LatexView,
        }),
        makeDefinition({
            tagName: 'Python',
            label: 'Python',
            category: 'Code',
            description: 'Python analysis block',
            icon: <IconCode />,
            defaultProps: { code: '', title: 'Python' },
            ViewComponent: CodeView,
        }),
        makeDefinition({
            tagName: 'DuckSQL',
            label: 'SQL (DuckDB)',
            category: 'Code',
            description: 'DuckDB SQL block',
            icon: <IconDatabase />,
            defaultProps: { code: '', returnVariable: 'duck_df', title: 'SQL (DuckDB)' },
            ViewComponent: CodeView,
        }),
        makeDefinition({
            tagName: 'HogQLSQL',
            label: 'SQL (HogQL)',
            category: 'Code',
            description: 'HogQL SQL block',
            icon: <IconDatabase />,
            defaultProps: { code: '', returnVariable: 'hogql_df', title: 'SQL (HogQL)' },
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

function ImageView({ node }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const alt = typeof node.props.alt === 'string' ? node.props.alt : ''

    return src ? (
        <img className="MarkdownNotebook__image" src={src} alt={alt} />
    ) : (
        <SummaryView node={node} mode="view" updateProps={() => {}} />
    )
}

function EmbedView({ node }: NotebookComponentRenderProps): JSX.Element {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const title = typeof node.props.title === 'string' ? node.props.title : 'Embedded content'

    return src ? (
        <iframe className="MarkdownNotebook__embed" src={src} title={title} sandbox="allow-scripts allow-same-origin" />
    ) : (
        <SummaryView node={node} mode="view" updateProps={() => {}} />
    )
}

function LatexView({ node }: NotebookComponentRenderProps): JSX.Element {
    const content = typeof node.props.content === 'string' ? node.props.content : ''
    return <div className="MarkdownNotebook__latex">{content}</div>
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
