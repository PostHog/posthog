import { memo, type PointerEvent as ReactPointerEvent, useCallback, useRef } from 'react'
import clsx from 'clsx'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'
import './NodeWrapper.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { hashCodeForString } from 'lib/utils/strings'
import { useInView } from 'react-intersection-observer'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { NotebookNodeLogicProps, notebookNodeLogic } from './notebookNodeLogic'
import { KNOWN_NODES } from '../utils'
import { NotebookNodeTitle } from './components/NotebookNodeTitle'
import { DuckSqlRunMenu } from './components/DuckSqlRunMenu'
import { HogqlSqlRunMenu } from './components/HogqlSqlRunMenu'
import { PythonRunMenu } from './components/PythonRunMenu'
import { NotebookNodeContext } from './NotebookNodeContext'
import { IconCollapse, IconCopy, IconEllipsis, IconExpand, IconPencil, IconX } from '@posthog/icons'
import {
    CreatePostHogWidgetNodeOptions,
    CustomNotebookNodeAttributes,
    NodeWrapperProps,
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
        attributes,
        updateAttributes,
        Settings = null,
    } = props

    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { isEditable, editingNodeIds, containerSize, notebook, isShared } = useValues(mountedNotebookLogic)
    const { unregisterNodeLogic, insertComment, selectComment } = useActions(notebookLogic)

    const logicProps: NotebookNodeLogicProps = {
        ...props,
        notebookLogic: mountedNotebookLogic,
    }

    // nodeId can start null, but should then immediately be generated
    const nodeLogic = useMountedLogic(notebookNodeLogic(logicProps))
    const {
        resizeable,
        expanded,
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
        toggleEditingTitle,
        copyToClipboard,
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

    const parsedHref = typeof href === 'function' ? href(attributes) : href

    // Element is resizable if resizable is set to true. If expandable is set to true then is is only resizable if expanded is true
    const isResizeable = resizeable && (!expandable || expanded)
    const onResizeHandlePointerDown = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>): void => {
            if (!isEditable || !isResizeable || !contentRef.current) {
                return
            }

            event.preventDefault()
            event.stopPropagation()

            const element = contentRef.current
            const startY = event.clientY
            const startHeight = element.getBoundingClientRect().height
            const parsedMinHeight = Number.parseFloat(window.getComputedStyle(element).minHeight)
            const minResizeHeight = Number.isFinite(parsedMinHeight) ? parsedMinHeight : 0

            const onPointerMove = (moveEvent: PointerEvent): void => {
                moveEvent.preventDefault()
                const nextHeight = Math.max(minResizeHeight, startHeight + moveEvent.clientY - startY)
                element.style.height = `${Math.round(nextHeight)}px`
            }

            const onPointerUp = (): void => {
                window.removeEventListener('pointermove', onPointerMove)
                window.removeEventListener('pointerup', onPointerUp)

                updateAttributes({
                    height: element.clientHeight,
                    ...(nodeType === NotebookNodeType.Python ? { autoHeight: false } : {}),
                } as any)
            }

            window.addEventListener('pointermove', onPointerMove)
            window.addEventListener('pointerup', onPointerUp)
        },
        [isEditable, isResizeable, nodeType, updateAttributes]
    )
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

    return (
        <NotebookNodeContext.Provider value={nodeLogic}>
            <BindLogic logic={notebookNodeLogic} props={logicProps}>
                <div>
                    <div
                        ref={setRefs}
                        className={clsx(nodeType, 'NotebookNode', {
                            'NotebookNode--auto-hide-metadata': autoHideMetadata,
                            'NotebookNode--selected': isEditable && selected,
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
                                        <div className="NotebookNode__meta">
                                            <div className="flex items-center flex-1 overflow-hidden">
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

                                                {isEditable && Settings ? (
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
                                                {isEditable && isResizeable ? (
                                                    <div
                                                        className="NotebookNode__resize-handle"
                                                        aria-hidden="true"
                                                        onPointerDown={onResizeHandlePointerDown}
                                                    />
                                                ) : null}
                                            </ErrorBoundary>
                                        </div>
                                    </>
                                )}
                            </ErrorBoundary>
                        </div>
                    </div>
                </div>
            </BindLogic>
        </NotebookNodeContext.Provider>
    )
}

export const MemoizedNodeWrapper = memo(NodeWrapper) as typeof NodeWrapper

/**
 * Registers a notebook node component so the markdown notebook registry (KNOWN_NODES)
 * can render it. The returned options are also the module's export for direct imports.
 */
export function createPostHogWidgetNode<T extends CustomNotebookNodeAttributes>(
    options: CreatePostHogWidgetNodeOptions<T>
): CreatePostHogWidgetNodeOptions<T> {
    KNOWN_NODES[options.nodeType] = options
    return options
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
