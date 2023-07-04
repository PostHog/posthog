import { Mark, mergeAttributes } from '@tiptap/core'
// import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookMarkType } from '~/types'
import { linkPasteRule } from '../Nodes/utils'
// import { Link } from '@posthog/lemon-ui'
// import { useCallback, useMemo } from 'react'
// import {
//     IconGauge,
//     IconBarChart,
//     IconRecording,
//     IconFlag,
//     IconRocketLaunch,
//     IconExperiment,
//     IconCoffee,
//     IconLive,
//     IconUnverifiedEvent,
//     IconPerson,
//     IconCohort,
//     IconComment,
//     // IconLink,
//     IconJournal,
// } from 'lib/lemon-ui/icons'
// import clsx from 'clsx'
// import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'
// import { useActions, useValues } from 'kea'
// import { notebookLogic } from '../Notebook/notebookLogic'

// const ICON_MAP = {
//     dashboard: <IconGauge />,
//     insight: <IconBarChart />,
//     recording: <IconRecording />,
//     feature_flags: <IconFlag />,
//     early_access_features: <IconRocketLaunch />,
//     experiments: <IconExperiment />,
//     notebooks: <IconJournal />,
//     'web-performance': <IconCoffee />,
//     events: <IconLive />,
//     'data-management': <IconUnverifiedEvent />,
//     persons: <IconPerson />,
//     groups: <IconPerson />,
//     cohorts: <IconCohort />,
//     annotations: <IconComment />,
// }

// const Component = (props: NodeViewProps): JSX.Element => {
//     const { shortId } = useValues(notebookLogic)
//     const { notebookSideBarShown } = useValues(notebookSidebarLogic)
//     const { setNotebookSideBarShown, selectNotebook } = useActions(notebookSidebarLogic)

//     const href: string = props.node.attrs.href

//     const [path, pathStart, internal] = useMemo(() => {
//         const path = href.replace(window.location.origin, '')
//         const pathStart = path.split('/')[1]?.toLowerCase()
//         const internal = href.startsWith(window.location.origin)

//         return [path, pathStart, internal]
//     }, [href])

//     const handleOnClick = useCallback(() => {
//         if (internal && !notebookSideBarShown) {
//             selectNotebook(shortId)
//             setNotebookSideBarShown(true)
//         }
//     }, [internal, shortId, setNotebookSideBarShown, selectNotebook])

//     return (
//         <NodeViewWrapper as="span">
//             <Link
//                 to={path}
//                 onClick={handleOnClick}
//                 target={internal ? undefined : '_blank'}
//                 className={clsx(
//                     'py-px px-1 rounded',
//                     props.selected && 'bg-primary-light',
//                     !props.selected && 'bg-primary-highlight'
//                 )}
//             >
//                 <span>{ICON_MAP[pathStart] || <IconLink />}</span>
//                 <span>{path}</span>
//             </Link>
//         </NodeViewWrapper>
//     )
// }

export const NotebookMarkLink = Mark.create({
    name: NotebookMarkType.Link,
    priority: 1000,
    keepOnSplit: false,

    // onCreate() {
    //     this.options.protocols.forEach(protocol => {
    //       if (typeof protocol === 'string') {
    //         registerCustomProtocol(protocol)
    //         return
    //       }
    //       registerCustomProtocol(protocol.scheme, protocol.optionalSlashes)
    //     })
    //   },

    //   onDestroy() {
    //     reset()
    //   },

    addAttributes() {
        return {
            href: {
                default: '',
            },
        }
    },

    parseHTML() {
        return [{ tag: 'a[href]:not([href *= "javascript:" i])' }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['a', mergeAttributes(HTMLAttributes), 0]
    },

    addPasteRules() {
        return [
            linkPasteRule({
                find: '(.+)',
                type: this.type,
                getAttributes: (match) => {
                    return { href: match[0] }
                },
            }),
            linkPasteRule({
                find: '(.+)',
                type: this.type,
                getAttributes: (match) => {
                    return { href: match[0] }
                },
            }),
        ]
    },
})
