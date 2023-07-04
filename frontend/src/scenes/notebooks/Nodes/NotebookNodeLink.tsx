import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookNodeType } from '~/types'
import { posthogNodePasteRule, externalLinkPasteRule } from './utils'
import { Link } from '@posthog/lemon-ui'
import { useCallback, useMemo } from 'react'
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
import clsx from 'clsx'
import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'
import { useActions, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'

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
    const { shortId } = useValues(notebookLogic)
    const { notebookSideBarShown } = useValues(notebookSidebarLogic)
    const { setNotebookSideBarShown, selectNotebook } = useActions(notebookSidebarLogic)

    const href: string = props.node.attrs.href

    const [path, pathStart, internal] = useMemo(() => {
        const path = href.replace(window.location.origin, '')
        const pathStart = path.split('/')[1]?.toLowerCase()
        const internal = href.startsWith(window.location.origin)

        return [path, pathStart, internal]
    }, [href])

    const handleOnClick = useCallback(() => {
        if (internal && !notebookSideBarShown) {
            selectNotebook(shortId)
            setNotebookSideBarShown(true)
        }
    }, [internal, shortId, setNotebookSideBarShown, selectNotebook])

    return (
        <NodeViewWrapper as="span">
            <Link
                to={path}
                onClick={handleOnClick}
                // target={external ? '_blank' : '_self'}
                className={clsx(
                    'py-px px-1 rounded',
                    props.selected && 'bg-primary-light',
                    !props.selected && 'bg-primary-highlight'
                )}
            >
                <span>{ICON_MAP[pathStart] || <IconLink />}</span> {path}
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
