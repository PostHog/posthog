import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { InsightModel, NotebookNodeType, NotebookTarget } from '~/types'
import { Link } from '@posthog/lemon-ui'
import { IconBarChart, IconFlag, IconExperiment, IconLive, IconPerson, IconCohort } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import clsx from 'clsx'
import { router } from 'kea-router'
import { posthogNodePasteRule } from './utils'
import api from 'lib/api'
import { useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'

import { openNotebook } from '~/models/notebooksModel'
import { IconChat, IconDashboard, IconLogomark, IconNotebook, IconRewindPlay } from '@posthog/icons'
import { useEffect } from 'react'

type BackLinkMapper = {
    regex: string
    type: string
    icon: JSX.Element
    getTitle: (match: string) => Promise<string>
}

const BACKLINK_MAP: BackLinkMapper[] = [
    {
        type: 'dashboards',
        regex: urls.dashboard('(.+)'),
        icon: <IconDashboard />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const dashboard = await api.dashboards.get(Number(id))
            return dashboard.name ?? ''
        },
    },
    {
        type: 'insights',
        regex: urls.insightView('(.+)' as InsightModel['short_id']),
        icon: <IconBarChart />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const insight = await api.insights.loadInsight(id as InsightModel['short_id'])
            return insight.results[0]?.name ?? ''
        },
    },
    {
        type: 'feature_flags',
        regex: urls.featureFlag('(.+)'),
        icon: <IconFlag />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const flag = await api.featureFlags.get(Number(id))
            return flag.name ?? ''
        },
    },
    {
        type: 'experiments',
        regex: urls.experiment('(.+)'),
        icon: <IconExperiment />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const experiment = await api.experiments.get(Number(id))
            return experiment.name ?? ''
        },
    },
    {
        type: 'surveys',
        regex: urls.survey('(.+)'),
        icon: <IconChat />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const survey = await api.surveys.get(id)
            return survey.name ?? ''
        },
    },
    {
        type: 'events',
        regex: urls.eventDefinition('(.+)'),
        icon: <IconLive width="1em" height="1em" />,
        getTitle: async (path: string) => {
            const id = path.split('/')[3]
            const event = await api.eventDefinitions.get({ eventDefinitionId: id })
            return event.name ?? ''
        },
    },
    {
        type: 'persons',
        regex: urls.personByDistinctId('(.+)'),
        icon: <IconPerson />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const response = await api.persons.list({ distinct_id: id })
            return response.results[0]?.name ?? ''
        },
    },
    {
        type: 'cohorts',
        regex: urls.cohort('(.+)'),
        icon: <IconCohort />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const cohort = await api.cohorts.get(Number(id))
            return cohort.name ?? ''
        },
    },
    {
        type: 'replay',
        regex: urls.replaySingle('(.+)'),
        icon: <IconRewindPlay />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            return id
        },
    },
    {
        type: 'notebooks',
        regex: urls.notebook('(.+)'),
        icon: <IconNotebook />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const notebook = await api.notebooks.get(id)
            return notebook.title ?? ''
        },
    },
]

const Component = (props: NodeViewProps): JSX.Element => {
    const { shortId } = useValues(notebookLogic)
    const { location } = useValues(router)

    const href: string = props.node.attrs.href ?? ''

    const backLinkConfig = BACKLINK_MAP.find((config) => href.match(config.regex))
    const derivedText: string = props.node.attrs.title || props.node.attrs.href
    const isViewing = location.pathname === href

    useEffect(() => {
        if (props.node.attrs.title || !backLinkConfig) {
            return
        }

        void backLinkConfig
            .getTitle(href)
            .then((title) => {
                props.updateAttributes({
                    title,
                })
            })
            .catch((e) => {
                console.error(e)
            })
    }, [props.node.attrs.title])

    return (
        <NodeViewWrapper
            as="span"
            className={clsx('Backlink', isViewing && 'Backlink--active', props.selected && 'Backlink--selected')}
        >
            <Link to={href} onClick={() => void openNotebook(shortId, NotebookTarget.Popover)} className="space-x-1">
                <span>{backLinkConfig?.icon || <IconLogomark />}</span>
                <span className="Backlink__label">{derivedText}</span>
            </Link>
        </NodeViewWrapper>
    )
}

export const NotebookNodeBacklink = Node.create({
    name: NotebookNodeType.Backlink,
    inline: true,
    group: 'inline',
    atom: true,

    addAttributes() {
        return {
            href: { default: '' },
            type: {},
            title: {},
        }
    },

    parseHTML() {
        return [{ tag: NotebookNodeType.Backlink }]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Backlink, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addPasteRules() {
        return [
            posthogNodePasteRule({
                find: '(.+)',
                editor: this.editor,
                type: this.type,
                getAttributes: async (match) => {
                    return { href: match[1] }
                },
            }),
        ]
    },
})
