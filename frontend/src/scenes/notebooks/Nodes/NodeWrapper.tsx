// sort-imports-ignore

// KLUDGE: Do NOT remove the `sort-imports-ignore` comment. It's used to sort the imports.
// Our KNOWN_NODES resolution will NOT work if the imports here are sorted in a different way.
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
import { IconDragHandle, IconLink } from 'lib/lemon-ui/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'
import './NodeWrapper.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { BindLogic, BuiltLogic, useActions, useMountedLogic, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useInView } from 'react-intersection-observer'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { NotebookNodeLogicProps, notebookNodeLogic } from './notebookNodeLogic'
import { posthogNodeInputRule, posthogNodePasteRule, useSyncedAttributes } from './utils'
import { KNOWN_NODES } from '../utils'
import { useWhyDidIRender } from 'lib/hooks/useWhyDidIRender'
import { NotebookNodeTitle } from './components/NotebookNodeTitle'
import { notebookNodeLogicType } from './notebookNodeLogicType'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import posthog from 'posthog-js'
import { NotebookNodeContext } from './NotebookNodeContext'
import { IconCollapse, IconCopy, IconEllipsis, IconExpand, IconFilter, IconGear, IconPlus, IconX } from '@posthog/icons'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    CreatePostHogWidgetNodeOptions,
    CustomNotebookNodeAttributes,
    NodeWrapperProps,
    NotebookNodeProps,
    NotebookNodeResource,
} from '../types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

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
    const { unregisterNodeLogic, insertComment, selectComment } = useActions(notebookLogic)
    const [slashCommandsPopoverVisible, setSlashCommandsPopoverVisible] = useState<boolean>(false)
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')

    const logicProps: NotebookNodeLogicProps = {
        ...props,
        notebookLogic: mountedNotebookLogic,
    }

    // nodeId can start null, but should then immediately be generated
    const nodeLogic = useMountedLogic(notebookNodeLogic(logicProps))
    const { resizeable, expanded, actions, nodeId, sourceComment } = useValues(nodeLogic)
    const {
        setRef,
        setExpanded,
        deleteNode,
        toggleEditing,
        insertOrSelectNextLine,
        toggleEditingTitle,
        copyToClipboard,
        convertToBacklink,
    } = useActions(nodeLogic)

    const { ref: inViewRef, inView } = useInView({ triggerOnce: true })

    const setRefs = useCallback(
        (node: HTMLDivElement | null) => {
            setRef(node)
            inViewRef(node)
        },
        // oxlint-disable-next-line exhaustive-deps
        [inViewRef]
    )

    // TRICKY: child nodes mount the parent logic so we need to control the mounting / unmounting directly in this component
    useOnMountEffect(() => {
        return () => unregisterNodeLogic(nodeId)
    })

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

    const menuItems: LemonMenuItems = [
        {
            label: 'Copy',
            onClick: () => copyToClipboard(),
            sideIcon: <IconCopy />,
        },
        isEditable && isResizeable
            ? {
                  label: 'Reset height to default',
                  onClick: () => {
                      updateAttributes({
                          height: null,
                      } as any)
                  },
              }
            : null,
        isEditable && parsedHref
            ? {
                  label: 'Convert to inline link',
                  onClick: () => convertToBacklink(parsedHref),
                  sideIcon: <IconLink />,
              }
            : null,
        isEditable ? { label: 'Edit title', onClick: () => toggleEditingTitle(true) } : null,
        isEditable && hasDiscussions
            ? sourceComment
                ? { label: 'Show comment', onClick: () => selectComment(nodeId) }
                : { label: 'Comment', onClick: () => insertComment({ type: 'node', id: nodeId }) }
            : null,
        isEditable ? { label: 'Remove', onClick: () => deleteNode(), sideIcon: <IconX />, status: 'danger' } : null,
    ]

    const hasMenu = menuItems.some((x) => !!x)

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
                                        <div className="h-10 p-2 flex justify-between">
                                            <LemonSkeleton className="w-1/4" />
                                            <LemonSkeleton className="w-20" />
                                        </div>
                                        {/* eslint-disable-next-line react/forbid-dom-props */}
                                        <div className="flex items-center p-2" style={{ height: heightEstimate }}>
                                            <LemonSkeleton className="w-full h-full" />
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

                                            <div className="flex deprecated-space-x-1">
                                                {parsedHref && (
                                                    <LemonButton size="small" icon={<IconLink />} to={parsedHref} />
                                                )}

                                                {expandable && (
                                                    <LemonButton
                                                        onClick={() => setExpanded(!expanded)}
                                                        size="small"
                                                        icon={expanded ? <IconCollapse /> : <IconExpand />}
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
                                                                        (settingsIcon ?? <IconFilter />)
                                                                    )
                                                                }
                                                                active={editingNodeId === nodeId}
                                                            />
                                                        ) : null}
                                                    </>
                                                ) : null}

                                                {hasMenu ? (
                                                    <LemonMenu items={menuItems} placement="bottom-end">
                                                        <LemonButton icon={<IconEllipsis />} size="small" />
                                                    </LemonMenu>
                                                ) : null}
                                            </div>
                                        </div>

                                        {Settings && editingNodeId === nodeId && containerSize === 'small' ? (
                                            <div className="NotebookNode__settings">
                                                <ErrorBoundary>
                                                    <Settings
                                                        key={nodeId}
                                                        attributes={attributes}
                                                        updateAttributes={updateAttributes}
                                                    />
                                                </ErrorBoundary>
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
                                            <ErrorBoundary>
                                                <Component
                                                    attributes={attributes}
                                                    updateAttributes={updateAttributes}
                                                />
                                            </ErrorBoundary>
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
                                        getPos={() => (getPos() ?? 0) + 1}
                                        visible={slashCommandsPopoverVisible}
                                        onClose={() => setSlashCommandsPopoverVisible(false)}
                                    >
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
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
    const { Component, pasteOptions, inputOptions, attributes, serializedText, ...wrapperProps } = options

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
            // oxlint-disable-next-line exhaustive-deps
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
            // We want to stringify all object attributes so that we can use them in the serializedText
            const sanitizedAttributes = Object.fromEntries(
                Object.entries(HTMLAttributes).map(([key, value]) => {
                    if (Array.isArray(value) || typeof value === 'object') {
                        return [key, JSON.stringify(value)]
                    }
                    return [key, value]
                })
            )

            // This method is primarily used by copy and paste so we can remove the nodeID, assuming we don't want duplicates
            delete sanitizedAttributes['nodeId']

            return [wrapperProps.nodeType, mergeAttributes(sanitizedAttributes)]
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

        addInputRules() {
            return inputOptions
                ? [
                      posthogNodeInputRule({
                          editor: this.editor,
                          type: this.type,
                          ...inputOptions,
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
