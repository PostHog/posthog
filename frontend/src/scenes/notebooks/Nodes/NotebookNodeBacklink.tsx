import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { InsightModel, NotebookNodeType } from '~/types'
import { Link } from '@posthog/lemon-ui'
import { IconGauge, IconBarChart, IconFlag, IconExperiment, IconLive, IconPerson, IconCohort } from 'lib/lemon-ui/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'
import { notebookLogic } from '../Notebook/notebookLogic'
import clsx from 'clsx'
import { router } from 'kea-router'
import { posthogNodePasteRule } from './utils'
import api from 'lib/api'

const ICON_MAP = {
    dashboards: <IconGauge />,
    insights: <IconBarChart />,
    feature_flags: <IconFlag />,
    experiments: <IconExperiment />,
    events: <IconLive width="1em" height="1em" />,
    persons: <IconPerson />,
    cohorts: <IconCohort />,
}

const Component = (props: NodeViewProps): JSX.Element => {
    const { shortId } = useValues(notebookLogic)
    const { notebookLinkClicked } = useActions(notebookSidebarLogic)

    const type: TaxonomicFilterGroupType = props.node.attrs.type
    const href: string | undefined = backlinkHref(props.node.attrs.id, type)
    const title: string = props.node.attrs.title

    const isViewing = router.values.location.pathname === href

    return (
        <NodeViewWrapper
            as="span"
            class={clsx('Backlink', isViewing && 'Backlink--active', props.selected && 'Backlink--selected')}
        >
            <Link to={href} onClick={() => notebookLinkClicked(shortId)} target={undefined} className="space-x-1">
                <span>{ICON_MAP[type]}</span>
                <span className="Backlink__label">{title}</span>
            </Link>
        </NodeViewWrapper>
    )
}

function backlinkHref(id: string, type: TaxonomicFilterGroupType): string | undefined {
    if (type === TaxonomicFilterGroupType.Events) {
        return urls.eventDefinition(id)
    } else if (type === TaxonomicFilterGroupType.Cohorts) {
        return urls.cohort(id)
    } else if (type === TaxonomicFilterGroupType.Persons) {
        return urls.person(id)
    } else if (type === TaxonomicFilterGroupType.Insights) {
        return urls.insightView(id as InsightModel['short_id'])
    } else if (type === TaxonomicFilterGroupType.FeatureFlags) {
        return urls.featureFlag(id)
    } else if (type === TaxonomicFilterGroupType.Experiments) {
        return urls.experiment(id)
    } else if (type === TaxonomicFilterGroupType.Dashboards) {
        return urls.dashboard(id)
    }
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
                type: this.type,
                getAttributes: async (match) => {
                    const id = match[1]
                    const event = await api.eventDefinitions.get({ eventDefinitionId: id })
                    return { id: id, type: TaxonomicFilterGroupType.Events, title: event.name }
                },
            }),
            // posthogNodePasteRule({
            //     // TODO: Regex to match all the supported types
            //     find: '(.+)',
            //     type: this.type,
            //     getAttributes: (match) => {
            //         // TODO: Figure out if we can get the title from some universal api request
            //         return { id: match[0], type: match[1], title: match[2] }
            //     },
            // }),
        ]
    },
})
