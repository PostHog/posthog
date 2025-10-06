import { Node, NodeViewProps, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import clsx from 'clsx'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import {
    IconChat,
    IconDashboard,
    IconFlag,
    IconFlask,
    IconGraph,
    IconLive,
    IconLogomark,
    IconNotebook,
    IconPeople,
    IconPerson,
    IconPlaylist,
    IconRewindPlay,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { openNotebook } from '~/models/notebooksModel'
import { QueryBasedInsightModel } from '~/types'

import { notebookLogic } from '../Notebook/notebookLogic'
import { NotebookNodeType, NotebookTarget } from '../types'
import { posthogNodePasteRule } from './utils'

type BackLinkMapper = {
    regex: RegExp
    type: string
    icon: JSX.Element
    getTitle: (match: string) => Promise<string>
}

const BACKLINK_MAP: BackLinkMapper[] = [
    {
        type: 'dashboards',
        regex: new RegExp(urls.dashboard('(.+)')),
        icon: <IconDashboard />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const dashboard = await api.dashboards.get(Number(id))
            return dashboard.name ?? ''
        },
    },
    {
        type: 'insights',
        regex: new RegExp(urls.insightView('(.+)' as QueryBasedInsightModel['short_id'])),
        icon: <IconGraph />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const insight = await api.insights.loadInsight(id as QueryBasedInsightModel['short_id'])
            return insight.results[0]?.name ?? ''
        },
    },
    {
        type: 'feature_flags',
        regex: new RegExp(urls.featureFlag('(.+)')),
        icon: <IconFlag />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const flag = await api.featureFlags.get(Number(id))
            return flag.name ?? ''
        },
    },
    {
        type: 'experiments',
        regex: new RegExp(urls.experiment('(.+)')),
        icon: <IconFlask />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const experiment = await api.experiments.get(Number(id))
            return experiment.name ?? ''
        },
    },
    {
        type: 'surveys',
        regex: new RegExp(urls.survey('(.+)')),
        icon: <IconChat />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const survey = await api.surveys.get(id)
            return survey.name ?? ''
        },
    },
    {
        type: 'events',
        regex: new RegExp(urls.eventDefinition('(.+)')),
        icon: <IconLive width="1em" height="1em" />,
        getTitle: async (path: string) => {
            const id = path.split('/')[3]
            const event = await api.eventDefinitions.get({ eventDefinitionId: id })
            return event.name ?? ''
        },
    },
    {
        type: 'persons',
        regex: new RegExp(urls.personByDistinctId('(.+)')),
        icon: <IconPerson />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const response = await api.persons.list({ distinct_id: id })
            return response.results[0]?.name ?? ''
        },
    },
    {
        type: 'cohorts',
        regex: new RegExp(urls.cohort('(.+)')),
        icon: <IconPeople />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            const cohort = await api.cohorts.get(Number(id))
            return cohort.name ?? ''
        },
    },
    {
        type: 'playlist',
        regex: new RegExp(urls.replayPlaylist('(.+)')),
        icon: <IconPlaylist />,
        getTitle: async (path: string) => {
            const id = path.split('/')[3]
            const playlist = await api.recordings.getPlaylist(id)
            return playlist.name ?? 'None'
        },
    },
    {
        type: 'replay',
        regex: new RegExp(urls.replaySingle('(.+)')),
        icon: <IconRewindPlay />,
        getTitle: async (path: string) => {
            const id = path.split('/')[2]
            return id
        },
    },
    {
        type: 'notebooks',
        regex: new RegExp(urls.notebook('(.+)')),
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

    const backLinkConfig = BACKLINK_MAP.find((config) => config.regex.test(href))
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
        // oxlint-disable-next-line exhaustive-deps
    }, [props.node.attrs.title])

    return (
        <NodeViewWrapper
            as="span"
            className={clsx('Backlink', isViewing && 'Backlink--active', props.selected && 'Backlink--selected')}
        >
            <Link
                to={href}
                onClick={() => void openNotebook(shortId, NotebookTarget.Popover)}
                className="deprecated-space-x-1"
            >
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
