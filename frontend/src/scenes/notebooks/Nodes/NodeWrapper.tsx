// KLUDGE: This file is NOT formatted by oxfmt to avoid problems with import resolutions.
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
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { hashCodeForString } from 'lib/utils'
import { useInView } from 'react-intersection-observer'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { NotebookNodeLogicProps, notebookNodeLogic } from './notebookNodeLogic'
import {
    posthogNodeInputRule,
    posthogNodePasteRule,
    shouldOmitFromClipboardHTML,
    useSyncedAttributes,
} from './utils'
import { KNOWN_NODES } from '../utils'
import { SharedNodeErrorBoundary, UnsupportedNodePlaceholder, isNodeSupportedInSharedNotebook } from './sharedNodeSupport'
import { NotebookNodeTitle } from './components/NotebookNodeTitle'
import { DuckSqlRunMenu } from './components/DuckSqlRunMenu'
import { HogqlSqlRunMenu } from './components/HogqlSqlRunMenu'
import { PythonRunMenu } from './components/PythonRunMenu'
import { SlashCommandsPopover } from '../Notebook/SlashCommands'
import posthog from 'posthog-js'
import { NotebookNodeContext } from './NotebookNodeContext'
import { IconCollapse, IconCopy, IconEllipsis, IconExpand, IconPencil, IconPlus, IconX } from '@posthog/icons'
import {
    CreatePostHogWidgetNodeOptions,
    CustomNotebookNodeAttributes,
    NodeWrapperProps,
    NotebookNodeProps,
    NotebookNodeResource,
    NotebookNodeType,
} from '../types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

const NON_COPYABLE_NODES = [
    NotebookNodeType.PersonProperties,
    NotebookNodeType.Person,
    NotebookNodeType.GroupProperties,
    NotebookNodeType.Group,
    NotebookNodeType.RelatedGroups,
]

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
    } = props

    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { isEditable, editingNodeIds, containerSize, notebook, mode, isShared } = useValues(mountedNotebookLogic)
    const { unregisterNodeLogic, insertComment, selectComment } = useActions(notebookLogic)
    const [slashCommandsPopoverVisible, setSlashCommandsPopoverVisible] = useState<boolean>(false)

    const logicProps: NotebookNodeLogicProps = {
        ...props,
        notebookLogic: mountedNotebookLogic,
    }

    // nodeId can start null, but should then immediately be generated
    const nodeLogic = useMountedLogic(notebookNodeLogic(logicProps))
    const {
        resizeable,
        expanded,
        actions,
        nodeId,
        pythonRunLoading,
        duckSqlRunLoading,
        duckSqlRunQueued,
        hogqlSqlRunLoading,
        hogqlSqlRunQueued,
        pythonRunQueued,
        settingsPlacement: resolvedSettingsPlacement,
        sourceComment,
        duckSqlReturnVariable,
        hogqlSqlReturnVariable,
        customMenuItems,
        kernelInfo,
    } = useValues(nodeLogic)
    const {
        setRef,
        setExpanded,
        deleteNode,
        toggleEditing,
        insertOrSelectNextLine,
        toggleEditingTitle,
        copyToClipboard,
        convertToBacklink,
        runPythonNodeWithMode,
        runDuckSqlNodeWithMode,
        runHogqlSqlNodeWithMode,
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
                    ...(nodeType === NotebookNodeType.Python ? { autoHeight: false } : {}),
                } as any)
            }
        }

        window.addEventListener('mouseup', onResizedEnd)
    }, [nodeType, resizeable, updateAttributes])

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
    const isPythonNode = nodeType === NotebookNodeType.Python
    const isDuckSqlNode = nodeType === NotebookNodeType.DuckSQL
    const isHogqlSqlNode = nodeType === NotebookNodeType.HogQLSQL
    const runDisabledReason = !notebook ? 'Notebook not loaded' : undefined
    const pythonAttributes = attributes as {
        code?: string
        pythonExecutionCodeHash?: number | null
        pythonExecutionSandboxId?: string | null
    }
    const pythonExecutionCodeHash = pythonAttributes.pythonExecutionCodeHash ?? null
    const pythonCodeHash = hashCodeForString(typeof pythonAttributes.code === 'string' ? pythonAttributes.code : '')
    const pythonExecutionSandboxId = pythonAttributes.pythonExecutionSandboxId ?? null
    const kernelSandboxId = kernelInfo?.sandbox_id ?? null
    const kernelIsRunning = kernelInfo?.status === 'running'
    const pythonHasExecution = pythonExecutionCodeHash !== null
    const pythonSandboxMatches =
        pythonExecutionSandboxId !== null && kernelSandboxId !== null && pythonExecutionSandboxId === kernelSandboxId
    const pythonIsFresh =
        pythonHasExecution && pythonExecutionCodeHash === pythonCodeHash && pythonSandboxMatches && kernelIsRunning
    const pythonIsStale = pythonHasExecution && !pythonIsFresh
    const duckSqlAttributes = attributes as {
        code?: string
        duckExecutionCodeHash?: number | null
        duckExecutionSandboxId?: string | null
        returnVariable?: string
    }
    const duckSqlExecutionCodeHash = duckSqlAttributes.duckExecutionCodeHash ?? null
    const duckSqlCodeHash = hashCodeForString(
        `${typeof duckSqlAttributes.code === 'string' ? duckSqlAttributes.code : ''}\n${duckSqlReturnVariable}`
    )
    const duckSqlExecutionSandboxId = duckSqlAttributes.duckExecutionSandboxId ?? null
    const duckSqlHasExecution = duckSqlExecutionCodeHash !== null
    const duckSqlSandboxMatches =
        duckSqlExecutionSandboxId !== null && kernelSandboxId !== null && duckSqlExecutionSandboxId === kernelSandboxId
    const duckSqlIsFresh =
        duckSqlHasExecution && duckSqlExecutionCodeHash === duckSqlCodeHash && duckSqlSandboxMatches && kernelIsRunning
    const duckSqlIsStale = duckSqlHasExecution && !duckSqlIsFresh
    const hogqlSqlAttributes = attributes as {
        code?: string
        hogqlExecutionCodeHash?: number | null
        hogqlExecutionSandboxId?: string | null
        returnVariable?: string
    }
    const hogqlSqlExecutionCodeHash = hogqlSqlAttributes.hogqlExecutionCodeHash ?? null
    const hogqlSqlCodeHash = hashCodeForString(`${hogqlSqlAttributes.code ?? ''}\n${hogqlSqlReturnVariable}`)
    const hogqlSqlExecutionSandboxId = hogqlSqlAttributes.hogqlExecutionSandboxId ?? null
    const hogqlSqlHasExecution = hogqlSqlExecutionCodeHash !== null
    const hogqlSqlSandboxMatches =
        hogqlSqlExecutionSandboxId !== null &&
        kernelSandboxId !== null &&
        hogqlSqlExecutionSandboxId === kernelSandboxId
    const hogqlSqlIsFresh =
        hogqlSqlHasExecution &&
        hogqlSqlExecutionCodeHash === hogqlSqlCodeHash &&
        hogqlSqlSandboxMatches &&
        kernelIsRunning
    const hogqlSqlIsStale = hogqlSqlHasExecution && !hogqlSqlIsFresh

    const defaultMenuItems: LemonMenuItems = [
        // Copy round-trips the node attrs through HTML for paste into another notebook — doesn't
        // make sense for an anonymous shared viewer who has no editor to paste into.
        !NON_COPYABLE_NODES.includes(nodeType) && !isShared
            ? {
                  label: 'Copy',
                  onClick: () => copyToClipboard(),
                  sideIcon: <IconCopy />,
              }
            : null,
        isEditable && isResizeable
            ? {
                  label: 'Reset height to default',
                  onClick: () => {
                      updateAttributes({
                          height: null,
                          ...(nodeType === NotebookNodeType.Python ? { autoHeight: true } : {}),
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
        isEditable
            ? sourceComment
                ? { label: 'Show comment', onClick: () => selectComment(nodeId) }
                : { label: 'Comment', onClick: () => insertComment({ type: 'node', id: nodeId }) }
            : null,
        isEditable ? { label: 'Remove', onClick: () => deleteNode(), sideIcon: <IconX />, status: 'danger' } : null,
    ]

    const menuItems = customMenuItems ?? defaultMenuItems

    const hasMenu = menuItems.some((x) => !!x)
    const isInCanvas = mode === 'canvas'

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
                                                {parsedHref && !isShared && (
                                                    <LemonButton
                                                        size="small"
                                                        icon={<IconLink />}
                                                        to={parsedHref}
                                                        tooltip="Open linked resource"
                                                    />
                                                )}

                                                {isPythonNode ? (
                                                    <PythonRunMenu
                                                        isFresh={pythonIsFresh}
                                                        isStale={pythonIsStale}
                                                        loading={pythonRunLoading}
                                                        queued={pythonRunQueued}
                                                        disabledReason={runDisabledReason}
                                                        onRun={(mode) => void runPythonNodeWithMode({ mode })}
                                                    />
                                                ) : null}

                                                {isDuckSqlNode ? (
                                                    <DuckSqlRunMenu
                                                        isFresh={duckSqlIsFresh}
                                                        isStale={duckSqlIsStale}
                                                        loading={duckSqlRunLoading}
                                                        queued={duckSqlRunQueued}
                                                        disabledReason={runDisabledReason}
                                                        onRun={(mode) => void runDuckSqlNodeWithMode({ mode })}
                                                    />
                                                ) : null}
                                                {isHogqlSqlNode ? (
                                                    <HogqlSqlRunMenu
                                                        isFresh={hogqlSqlIsFresh}
                                                        isStale={hogqlSqlIsStale}
                                                        loading={hogqlSqlRunLoading}
                                                        queued={hogqlSqlRunQueued}
                                                        disabledReason={runDisabledReason}
                                                        onRun={(mode) => void runHogqlSqlNodeWithMode({ mode })}
                                                    />
                                                ) : null}

                                                {(isEditable || isInCanvas) && Settings ? (
                                                    <LemonButton
                                                        onClick={() => toggleEditing()}
                                                        size="small"
                                                        icon={<IconPencil />}
                                                        active={editingNodeIds[nodeId]}
                                                        tooltip={
                                                            editingNodeIds[nodeId]
                                                                ? 'Hide editor'
                                                                : 'Show editor and settings'
                                                        }
                                                        data-attr="notebook-node-edit-settings"
                                                    />
                                                ) : null}

                                                {expandable && (
                                                    <LemonButton
                                                        onClick={() => setExpanded(!expanded)}
                                                        size="small"
                                                        icon={expanded ? <IconCollapse /> : <IconExpand />}
                                                        tooltip={expanded ? 'Hide output' : 'Show output'}
                                                    />
                                                )}

                                                {hasMenu ? (
                                                    <LemonMenu items={menuItems} placement="bottom-end">
                                                        <LemonButton
                                                            icon={<IconEllipsis />}
                                                            size="small"
                                                            tooltip="More actions"
                                                        />
                                                    </LemonMenu>
                                                ) : null}
                                            </div>
                                        </div>

                                        {Settings &&
                                        !isShared &&
                                        editingNodeIds[nodeId] &&
                                        (containerSize === 'small' || resolvedSettingsPlacement === 'inline') ? (
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
                                            tooltip="Add block"
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
                                            tooltip={x.text}
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
        // Hooks must run unconditionally on every render — keep all hook calls above any early
        // return so the shared-notebook placeholder fast-path doesn't violate the rules of hooks.
        const { isShared } = useValues(notebookLogic)
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

        // when in shared mode, do not render any nodes that we know are unsupported
        if (isShared && !isNodeSupportedInSharedNotebook(wrapperProps.nodeType)) {
            return <UnsupportedNodePlaceholder />
        }

        const nodeProps: NotebookNodeProps<T> & Omit<NodeViewProps, 'attributes' | 'updateAttributes'> = {
            ...props,
            attributes,
            updateAttributes,
        }

        if (isShared) {
            // the error boundary renders the placeholder when there is an error instead of showing a bunch of random errors to the user
            return (
                <SharedNodeErrorBoundary>
                    <MemoizedNodeWrapper Component={Component} {...nodeProps} {...wrapperProps} />
                </SharedNodeErrorBoundary>
            )
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
            // All exposed attributes round-trip through HTML as JSON.
            // `parseHTML` on the way in and `renderHTML` on the way out are symmetric
            // so default Cmd+C and the explicit `copyToClipboard` action produce the same encoding and parse cleanly
            const jsonAttr = (name: string): Record<string, any> => ({
                parseHTML: (element: HTMLElement) => {
                    const raw = element.getAttribute(name)
                    return raw ? JSON.parse(raw) : null
                },
                renderHTML: (attrs: Record<string, any>) => {
                    const value = attrs[name]
                    if (value === null || value === undefined) {
                        return {}
                    }
                    return { [name]: JSON.stringify(value) }
                },
            })

            const nodeAttributes = Object.fromEntries(
                Object.entries(attributes as Record<string, any>).map(([name, config]) => {
                    return [
                        name,
                        {
                            ...config,
                            ...jsonAttr(name),
                        },
                    ]
                })
            )

            return {
                height: jsonAttr('height'),
                title: jsonAttr('title'),
                nodeId: {
                    default: null,
                },
                __init: { default: null },
                children: jsonAttr('children'),
                ...nodeAttributes,
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
            // Per-attribute renderHTML callbacks already JSON-stringified each value;
            // here we just apply the same omit rule the explicit Copy action uses
            const sanitized = Object.fromEntries(
                Object.entries(HTMLAttributes).filter(([key, value]) => !shouldOmitFromClipboardHTML(key, value))
            )
            return [wrapperProps.nodeType, mergeAttributes(sanitized)]
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
    // nodeLogic: nodeLogic,
    content,
}: {
    // nodeLogic: BuiltLogic<notebookNodeLogicType>
    content: NotebookNodeResource
}): JSX.Element => {
    const options = KNOWN_NODES[content.type]

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
            updateAttributes={() => undefined}
            selected={false}
        />
    )
}
