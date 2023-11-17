import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { InsightModel, NotebookNodeType, NotebookTarget } from '~/types'
import { Link } from '@posthog/lemon-ui'
import { IconGauge, IconBarChart, IconFlag, IconExperiment, IconLive, IconPerson, IconCohort } from 'lib/lemon-ui/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { urls } from 'scenes/urls'
import clsx from 'clsx'
import { router } from 'kea-router'
import { posthogNodePasteRule } from './utils'
import api from 'lib/api'
import { useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'

import { openNotebook } from '~/models/notebooksModel'
import { IconNotebook } from '../IconNotebook'

const ICON_MAP = {
    dashboards: <IconGauge />,
    insights: <IconBarChart />,
    feature_flags: <IconFlag />,
    experiments: <IconExperiment />,
    events: <IconLive width="1em" height="1em" />,
    persons: <IconPerson />,
    cohorts: <IconCohort />,
    notebooks: <IconNotebook />,
}

const Component = (props: NodeViewProps): JSX.Element => {
    const { shortId } = useValues(notebookLogic)

    const type: TaxonomicFilterGroupType = props.node.attrs.type
    const title: string = props.node.attrs.title
    const id: string = props.node.attrs.id
    const href = backlinkHref(id, type)

    const isViewing = router.values.location.pathname === href

    return (
        <NodeViewWrapper
            as="span"
            className={clsx('Backlink', isViewing && 'Backlink--active', props.selected && 'Backlink--selected')}
        >
            <Link
                to={href}
                onClick={() => void openNotebook(shortId, NotebookTarget.Popover)}
                target={undefined}
                className="space-x-1"
            >
                <span>{ICON_MAP[type]}</span>
                <span className="Backlink__label">{title}</span>
            </Link>
        </NodeViewWrapper>
    )
}

function backlinkHref(id: string, type: TaxonomicFilterGroupType): string {
    if (type === TaxonomicFilterGroupType.Events) {
        return urls.eventDefinition(id)
    } else if (type === TaxonomicFilterGroupType.Cohorts) {
        return urls.cohort(id)
    } else if (type === TaxonomicFilterGroupType.Persons) {
        return urls.personByDistinctId(id)
    } else if (type === TaxonomicFilterGroupType.Insights) {
        return urls.insightView(id as InsightModel['short_id'])
    } else if (type === TaxonomicFilterGroupType.FeatureFlags) {
        return urls.featureFlag(id)
    } else if (type === TaxonomicFilterGroupType.Experiments) {
        return urls.experiment(id)
    } else if (type === TaxonomicFilterGroupType.Dashboards) {
        return urls.dashboard(id)
    } else if (type === TaxonomicFilterGroupType.Notebooks) {
        return urls.notebook(id)
    }
    return ''
}

export const NotebookNodeBacklink = Node.create({
    name: NotebookNodeType.Backlink,
    inline: true,
    group: 'inline',
    atom: true,

    addAttributes() {
        return {
            id: { default: '' },
            type: { default: '' },
            title: { default: '' },
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
                find: urls.eventDefinition('(.+)'),
                editor: this.editor,
                type: this.type,
                getAttributes: async (match) => {
                    const id = match[1]
                    const event = await api.eventDefinitions.get({ eventDefinitionId: id })
                    return { id: id, type: TaxonomicFilterGroupType.Events, title: event.name }
                },
            }),
            posthogNodePasteRule({
                find: urls.cohort('(.+)'),
                editor: this.editor,
                type: this.type,
                getAttributes: async (match) => {
                    const id = match[1]
                    const event = await api.cohorts.get(Number(id))
                    return { id: id, type: TaxonomicFilterGroupType.Cohorts, title: event.name }
                },
            }),
            posthogNodePasteRule({
                find: urls.experiment('(.+)'),
                editor: this.editor,
                type: this.type,
                getAttributes: async (match) => {
                    const id = match[1]
                    const experiment = await api.experiments.get(Number(id))
                    return { id: id, type: TaxonomicFilterGroupType.Experiments, title: experiment.name }
                },
            }),
            posthogNodePasteRule({
                find: urls.dashboard('(.+)'),
                editor: this.editor,
                type: this.type,
                getAttributes: async (match) => {
                    const id = match[1]
                    const dashboard = await api.dashboards.get(Number(id))
                    return { id: id, type: TaxonomicFilterGroupType.Dashboards, title: dashboard.name }
                },
            }),
            posthogNodePasteRule({
                find: urls.notebook('(.+)'),
                editor: this.editor,
                type: this.type,
                getAttributes: async (match) => {
                    const id = match[1]
                    const notebook = await api.notebooks.get(id)
                    return { id: id, type: TaxonomicFilterGroupType.Notebooks, title: notebook.title }
                },
            }),
        ]
    },
})
