import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { InsightModel, NotebookNodeType, NotebookTarget } from '~/types'
import { Link } from '@posthog/lemon-ui'
import { IconGauge, IconBarChart, IconFlag, IconExperiment, IconLive, IconPerson, IconCohort } from 'lib/lemon-ui/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { urls } from 'scenes/urls'
import clsx from 'clsx'
import { router } from 'kea-router'
import { openNotebook } from '../Notebook/notebooksListLogic'
import { useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'

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

    const type: TaxonomicFilterGroupType = props.node.attrs.type
    const title: string = props.node.attrs.title
    const id: string = props.node.attrs.id
    const href = backlinkHref(id, type)

    const isViewing = router.values.location.pathname === href

    return (
        <NodeViewWrapper
            as="span"
            class={clsx('Backlink', isViewing && 'Backlink--active', props.selected && 'Backlink--selected')}
        >
            <Link
                to={href}
                onClick={() => openNotebook(shortId, NotebookTarget.Sidebar)}
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
        return [
            {
                tag: NotebookNodeType.Backlink,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Backlink, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
