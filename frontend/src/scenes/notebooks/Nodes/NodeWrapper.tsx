import {
    Node,
    NodeViewWrapper,
    mergeAttributes,
    ReactNodeViewRenderer,
    NodeViewProps,
    getExtensionField,
} from '@tiptap/react'
import { memo, useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import {
    IconClose,
    IconDragHandle,
    IconFilter,
    IconLink,
    IconPlus,
    IconUnfoldLess,
    IconUnfoldMore,
} from 'lib/lemon-ui/icons'
import { LemonButton } from '@posthog/lemon-ui'
import './NodeWrapper.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { BindLogic, BuiltLogic, useActions, useMountedLogic, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useInView } from 'react-intersection-observer'
import { NotebookNodeResource } from '~/types'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { NotebookNodeLogicProps, notebookNodeLogic } from './notebookNodeLogic'
import { posthogNodePasteRule, useSyncedAttributes } from './utils'
import {
    KNOWN_NODES,
    NotebookNodeProps,
    CustomNotebookNodeAttributes,
    CreatePostHogWidgetNodeOptions,
    NodeWrapperProps,
} from '../Notebook/utils'
import { useWhyDidIRender } from 'lib/hooks/useWhyDidIRender'
import { NotebookNodeTitle } from './components/NotebookNodeTitle'
import { notebookNodeLogicType } from './notebookNodeLogicType'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import posthog from 'posthog-js'
import { NotebookNodeContext } from './NotebookNodeContext'
import { IconGear } from '@posthog/icons'

function NodeWrapper<T extends CustomNotebookNodeAttributes>(props: NodeWrapperProps<T>): JSX.Element {
    const {
        nodeType,
        Component,
        selected,
        href,
        heightEstimate = '4rem',
        expandable = true,
        expandOnClick = true,
        autoHideMetadata = false,
        minHeight,
        getPos,
        attributes,
        updateAttributes,
        Settings = null,
        settingsIcon,
    } = props

    useWhyDidIRender('NodeWrapper.props', props)

    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { isEditable, editingNodeId, containerSize } = useValues(mountedNotebookLogic)
    const { unregisterNodeLogic } = useActions(notebookLogic)
    const [slashCommandsPopoverVisible, setSlashCommandsPopoverVisible] = useState<boolean>(false)

    const logicProps: NotebookNodeLogicProps = {
        ...props,
        notebookLogic: mountedNotebookLogic,
    }

    // nodeId can start null, but should then immediately be generated
    const nodeLogic = useMountedLogic(notebookNodeLogic(logicProps))
    const { resizeable, expanded, actions, nodeId } = useValues(nodeLogic)
    const { setRef, setExpanded, deleteNode, toggleEditing, insertOrSelectNextLine } = useActions(nodeLogic)

    const { ref: inViewRef, inView } = useInView({ triggerOnce: true })

    const setRefs = useCallback(
        (node) => {
            setRef(node)
            inViewRef(node)
        },
        [inViewRef]
    )

    useEffect(() => {
        // TRICKY: child nodes mount the parent logic so we need to control the mounting / unmounting directly in this component
        return () => unregisterNodeLogic(nodeId)
    }, [])

    useWhyDidIRender('NodeWrapper.logicProps', {
        resizeable,
        expanded,
        actions,
        setExpanded,
        deleteNode,
        toggleEditing,
        mountedNotebookLogic,
    })

    const contentRef = useRef<HTMLDivElement | null>(null)

    // If resizeable is true then the node attr "height" is required
    const height = attributes.height ?? heightEstimate

    const onResizeStart = useCallback((): void => {
        if (!resizeable) {
            return
        }
        const initialHeightAttr = contentRef.current?.style.height
        const onResizedEnd = (): void => {
            window.removeEventListener('mouseup', onResizedEnd)
            // css resize sets the style attr so we check that to detect changes. Resize obsserver doesn't trigger for style changes
            const heightAttr = contentRef.current?.style.height
            if (heightAttr && heightAttr !== initialHeightAttr) {
                updateAttributes({
                    height: contentRef.current?.clientHeight,
                } as any)
            }
        }

        window.addEventListener('mouseup', onResizedEnd)
    }, [resizeable, updateAttributes])

    const onActionsAreaClick = (): void => {
        // Clicking in the area of the actions without selecting a specific action likely indicates the user wants to
        // add new content below. If we are in editing mode, we should select the next line if there is one, otherwise
        if (!slashCommandsPopoverVisible) {
            insertOrSelectNextLine()
        }
    }

    const parsedHref = typeof href === 'function' ? href(attributes) : href

    // Element is resizable if resizable is set to true. If expandable is set to true then is is only resizable if expanded is true
    const isResizeable = resizeable && (!expandable || expanded)
    const isDraggable = !!(isEditable && getPos)

    return (
        <NotebookNodeContext.Provider value={nodeLogic}>
            <BindLogic logic={notebookNodeLogic} props={logicProps}>
                <NodeViewWrapper as="div">
                    <div
                        ref={setRefs}
                        className={clsx(nodeType, 'NotebookNode', {
                            'NotebookNode--auto-hide-metadata': autoHideMetadata,
                            'NotebookNode--editable': getPos && isEditable,
                            'NotebookNode--selected': isEditable && selected,
                            'NotebookNode--active': slashCommandsPopoverVisible,
                        })}
                    >
                        <div className="NotebookNode__box">
                            <ErrorBoundary>
                                {!inView ? (
                                    <>
                                        <div className="h-10" /> {/* Placeholder for the drag handle */}
                                        {/* eslint-disable-next-line react/forbid-dom-props */}
                                        <div style={{ height: heightEstimate }}>
                                            <LemonSkeleton className="h-full" />
                                        </div>
                                    </>
                                ) : (
                                    <>
                                        <div className="NotebookNode__meta" data-drag-handle>
                                            <div className="flex items-center flex-1 overflow-hidden">
                                                {isDraggable && (
                                                    <IconDragHandle className="cursor-move text-base shrink-0" />
                                                )}
                                                <NotebookNodeTitle />
                                            </div>

                                            <div className="flex space-x-1">
                                                {parsedHref && (
                                                    <LemonButton size="small" icon={<IconLink />} to={parsedHref} />
                                                )}

                                                {expandable && (
                                                    <LemonButton
                                                        onClick={() => setExpanded(!expanded)}
                                                        size="small"
                                                        icon={expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                                    />
                                                )}

                                                {isEditable ? (
                                                    <>
                                                        {Settings ? (
                                                            <LemonButton
                                                                onClick={() => toggleEditing()}
                                                                size="small"
                                                                icon={
                                                                    typeof settingsIcon === 'string' ? (
                                                                        settingsIcon === 'gear' ? (
                                                                            <IconGear />
                                                                        ) : (
                                                                            <IconFilter />
                                                                        )
                                                                    ) : (
                                                                        settingsIcon ?? <IconFilter />
                                                                    )
                                                                }
                                                                active={editingNodeId === nodeId}
                                                            />
                                                        ) : null}

                                                        <LemonButton
                                                            onClick={() => deleteNode()}
                                                            size="small"
                                                            status="danger"
                                                            icon={<IconClose />}
                                                        />
                                                    </>
                                                ) : null}
                                            </div>
                                        </div>

                                        {Settings && editingNodeId === nodeId && containerSize === 'small' ? (
                                            <div className="NotebookNode__settings">
                                                <Settings
                                                    key={nodeId}
                                                    attributes={attributes}
                                                    updateAttributes={updateAttributes}
                                                />
                                            </div>
                                        ) : null}

                                        <div
                                            ref={contentRef}
                                            className={clsx(
                                                'NotebookNode__content flex flex-col relative z-0 overflow-hidden',
                                                isEditable && isResizeable && 'resize-y'
                                            )}
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={isResizeable ? { height, minHeight } : {}}
                                            onClick={!expanded && expandOnClick ? () => setExpanded(true) : undefined}
                                            onMouseDown={onResizeStart}
                                        >
                                            <Component attributes={attributes} updateAttributes={updateAttributes} />
                                        </div>
                                    </>
                                )}
                            </ErrorBoundary>
                        </div>
                        <div
                            className="NotebookNode__gap"
                            // UX improvement so that the actions don't get in the way of the cursor
                            onClick={() => onActionsAreaClick()}
                        >
                            {getPos && isEditable ? (
                                <>
                                    <SlashCommandsPopover
                                        mode="add"
                                        getPos={() => getPos() + 1}
                                        visible={slashCommandsPopoverVisible}
                                        onClose={() => setSlashCommandsPopoverVisible(false)}
                                    >
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            status="primary"
                                            icon={<IconPlus />}
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                setSlashCommandsPopoverVisible(true)
                                            }}
                                        />
                                    </SlashCommandsPopover>
                                    {actions.map((x, i) => (
                                        <LemonButton
                                            key={i}
                                            size="xsmall"
                                            type="secondary"
                                            status="primary"
                                            icon={x.icon ?? <IconPlus />}
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                x.onClick()
                                            }}
                                        >
                                            {x.text}
                                        </LemonButton>
                                    ))}
                                </>
                            ) : null}
                        </div>
                    </div>
                </NodeViewWrapper>
            </BindLogic>
        </NotebookNodeContext.Provider>
    )
}

export const MemoizedNodeWrapper = memo(NodeWrapper) as typeof NodeWrapper

export function createPostHogWidgetNode<T extends CustomNotebookNodeAttributes>(
    options: CreatePostHogWidgetNodeOptions<T>
): Node {
    const { Component, pasteOptions, attributes, serializedText, ...wrapperProps } = options

    KNOWN_NODES[wrapperProps.nodeType] = options

    // NOTE: We use NodeViewProps here as we convert them to NotebookNodeProps
    const WrappedComponent = (props: NodeViewProps): JSX.Element => {
        useWhyDidIRender('NodeWrapper(WrappedComponent)', props)
        const [attributes, updateAttributes] = useSyncedAttributes<T>(props)

        if (props.node.attrs.nodeId === null) {
            // TODO only wrapped in setTimeout because of the flushSync bug
            setTimeout(() => {
                props.updateAttributes({
                    nodeId: attributes.nodeId,
                })
            }, 0)
        }

        useEffect(() => {
            if (props.node.attrs.nodeId === null) {
                posthog.capture('notebook node added', { node_type: props.node.type.name })
            }
        }, [props.node.attrs.nodeId])

        const nodeProps: NotebookNodeProps<T> & Omit<NodeViewProps, 'attributes' | 'updateAttributes'> = {
            ...props,
            attributes,
            updateAttributes,
        }

        return <MemoizedNodeWrapper Component={Component} {...nodeProps} {...wrapperProps} />
    }

    return Node.create({
        name: wrapperProps.nodeType,
        group: 'block',
        atom: true,
        draggable: true,

        serializedText: serializedText,

        extendNodeSchema(extension) {
            const context = {
                name: extension.name,
                options: extension.options,
                storage: extension.storage,
            }
            return {
                serializedText: getExtensionField(extension, 'serializedText', context),
            }
        },

        addAttributes() {
            return {
                height: {},
                title: {},
                nodeId: {
                    default: null,
                },
                __init: { default: null },
                children: {},
                ...attributes,
            }
        },

        parseHTML() {
            return [
                {
                    tag: wrapperProps.nodeType,
                },
            ]
        },

        renderHTML({ HTMLAttributes }) {
            return [wrapperProps.nodeType, mergeAttributes(HTMLAttributes)]
        },

        addNodeView() {
            return ReactNodeViewRenderer(WrappedComponent)
        },

        addPasteRules() {
            return pasteOptions
                ? [
                      posthogNodePasteRule({
                          editor: this.editor,
                          type: this.type,
                          ...pasteOptions,
                      }),
                  ]
                : []
        },
    })
}

export const NotebookNodeChildRenderer = ({
    nodeLogic,
    content,
}: {
    nodeLogic: BuiltLogic<notebookNodeLogicType>
    content: NotebookNodeResource
}): JSX.Element => {
    const options = KNOWN_NODES[content.type]

    // eslint-disable-next-line no-console
    console.log(nodeLogic)
    // TODO: Respect attr changes

    // TODO: Allow deletion

    return (
        <MemoizedNodeWrapper
            {...options}
            // parentNodeLogic={nodeLogic}
            Component={options.Component}
            nodeType={content.type}
            titlePlaceholder={options.titlePlaceholder}
            attributes={content.attrs}
            updateAttributes={(newAttrs) => {
                // eslint-disable-next-line no-console
                console.log('updated called (TODO)', newAttrs)
            }}
            selected={false}
        />
    )
}
