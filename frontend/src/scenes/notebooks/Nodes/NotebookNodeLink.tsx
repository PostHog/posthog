import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookNodeType } from '~/types'
import { posthogNodePasteRule, externalLinkPasteRule } from './utils'
import { Link } from '@posthog/lemon-ui'
import {
    IconGauge,
    IconBarChart,
    IconRecording,
    IconFlag,
    IconRocketLaunch,
    IconExperiment,
    IconCoffee,
    IconLive,
    IconUnverifiedEvent,
    IconPerson,
    IconCohort,
    IconComment,
    IconLink,
    IconJournal,
} from 'lib/lemon-ui/icons'
import { useNotebookLink } from '../Notebook/Editor'
import { useMemo } from 'react'

const ICON_MAP = {
    dashboard: <IconGauge />,
    insight: <IconBarChart />,
    recording: <IconRecording />,
    feature_flags: <IconFlag />,
    early_access_features: <IconRocketLaunch />,
    experiments: <IconExperiment />,
    notebooks: <IconJournal />,
    'web-performance': <IconCoffee />,
    events: <IconLive />,
    'data-management': <IconUnverifiedEvent />,
    persons: <IconPerson />,
    groups: <IconPerson />,
    cohorts: <IconCohort />,
    annotations: <IconComment />,
}

const Component = (props: NodeViewProps): JSX.Element => {
    const href: string = props.node.attrs.href
    const { onClick } = useNotebookLink(href)

    const [path, pathStart] = useMemo(() => {
        const path = href.replace(window.location.origin, '')
        const pathStart = path.split('/')[1]?.toLowerCase()

        return [path, pathStart]
    }, [href])

    return (
        <NodeViewWrapper as="span">
            <Link onClick={onClick} className="p-1 rounded">
                <span>{ICON_MAP[pathStart] || <IconLink />}</span>
                <span>{path}</span>
            </Link>
        </NodeViewWrapper>
    )
}

export const NotebookNodeLink = Node.create({
    name: NotebookNodeType.Link,
    inline: true,
    group: 'inline',
    atom: true,

    addAttributes() {
        return {
            href: {
                default: '',
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.Link,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Link, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addPasteRules() {
        return [
            posthogNodePasteRule({
                find: '(.+)',
                type: this.type,
                getAttributes: (match) => {
                    return { href: match[0] }
                },
            }),
            externalLinkPasteRule({
                find: '(.+)',
                type: this.type,
                getAttributes: (match) => {
                    return { href: match[0] }
                },
            }),
        ]
    },
})
