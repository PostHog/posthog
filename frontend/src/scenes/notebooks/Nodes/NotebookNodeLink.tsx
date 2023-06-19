import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookNodeType } from '~/types'
import { posthogNodePasteRule } from './utils'
import { Link } from '@posthog/lemon-ui'
import { useMemo } from 'react'
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
} from 'lib/lemon-ui/icons'
import clsx from 'clsx'

const ICON_MAP = {
    dashboard: <IconGauge />,
    insight: <IconBarChart />,
    recording: <IconRecording />,
    feature_flags: <IconFlag />,
    early_access_features: <IconRocketLaunch />,
    experiments: <IconExperiment />,
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

    const [path, icon] = useMemo(() => {
        const path = href.replace(window.location.origin, '')
        const pathStart = path.split('/')[1]?.toLowerCase()

        return [path, ICON_MAP[pathStart] || <IconLink />]
    }, [href])

    return (
        <NodeViewWrapper as="span">
            <Link
                to={path}
                className={clsx(
                    'py-px px-1 rounded',
                    props.selected && 'bg-primary-light text-white',
                    !props.selected && 'bg-primary-highlight'
                )}
            >
                <span>{icon}</span> {path}
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
        ]
    },
})
