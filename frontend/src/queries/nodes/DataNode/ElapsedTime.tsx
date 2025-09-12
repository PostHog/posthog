import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { Popover } from 'lib/lemon-ui/Popover'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryTiming } from '~/queries/schema/schema-general'

export interface TimingsProps {
    timings: QueryTiming[]
    elapsedTime?: number
}

export function Timings({ timings, elapsedTime }: TimingsProps): JSX.Element | null {
    type TimingTreeNode = {
        name: string
        fullPath: string
        time?: number
        endTime: number
        children: TimingTreeNode[]
    }

    const { rootNodes, maxTime } = useMemo(() => {
        const root: {
            childrenMap: Map<string, TimingTreeNode & { childrenMap: Map<string, any> }>
            children: TimingTreeNode[]
        } = {
            childrenMap: new Map(),
            children: [],
        }

        const getOrCreateChild = (
            parent: typeof root | (TimingTreeNode & { childrenMap: Map<string, any> }),
            name: string,
            fullPath: string
        ): TimingTreeNode & { childrenMap: Map<string, any> } => {
            const existing = parent.childrenMap.get(name)
            if (existing) {
                return existing
            }
            const created: TimingTreeNode & { childrenMap: Map<string, any> } = {
                name,
                fullPath,
                endTime: 0,
                children: [],
                childrenMap: new Map(),
            }
            parent.childrenMap.set(name, created)
            parent.children.push(created)
            return created
        }

        timings.forEach(({ k, t }) => {
            const isDotOnly = k === '.'
            const normalized = isDotOnly ? ['.'] : k.replace(/^\.\//, '').split('/')
            let parent: any = root
            let path = ''
            normalized.forEach((segment, index) => {
                path = path ? `${path}/${segment}` : segment
                const node = getOrCreateChild(parent, segment, isDotOnly ? '.' : path)
                // update endTime along the path to allow groups to show total time of descendants
                if (t > node.endTime) {
                    node.endTime = t
                }
                if (index === normalized.length - 1) {
                    node.time = t
                }
                parent = node
            })
        })

        const detachMaps = (nodes: (TimingTreeNode & { childrenMap: Map<string, any> })[]): TimingTreeNode[] => {
            return nodes.map((n) => {
                const { childrenMap, ...rest } = n as any
                ;(rest as TimingTreeNode).children = detachMaps(n.children as any as any)
                return rest as TimingTreeNode
            })
        }

        return {
            rootNodes: detachMaps(root.children as any),
            maxTime: timings.length ? timings[timings.length - 1].t : 0,
        }
    }, [timings])

    const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['']))

    const toggle = (path: string): void => {
        setExpanded((prev) => {
            const next = new Set(prev)
            if (next.has(path)) {
                next.delete(path)
            } else {
                next.add(path)
            }
            return next
        })
    }

    const renderNode = (node: TimingTreeNode, depth: number): JSX.Element[] => {
        const isGroup = node.children.length > 0
        const pathKey = node.fullPath || node.name
        const isExpanded = expanded.has(pathKey)
        const displayTime = node.time ?? node.endTime
        const row = (
            <div
                key={pathKey}
                className={clsx(
                    'flex justify-between items-start deprecated-space-x-2 py-1.5',
                    displayTime > maxTime * 0.5 ? 'font-bold' : ''
                )}
            >
                <div
                    className={clsx(
                        'flex items-center gap-1.5',
                        isGroup ? 'cursor-pointer' : 'cursor-default',
                        depth > 0 ? 'border-l-2 border-border' : ''
                    )}
                    style={{ paddingLeft: depth * 32 }}
                    onClick={() => (isGroup ? toggle(pathKey) : undefined)}
                >
                    {isGroup ? (
                        <IconChevronRight className={clsx('transition-transform', isExpanded ? 'rotate-90' : '')} />
                    ) : null}
                    <span>{pathKey === '.' ? 'Query total' : node.name}</span>
                </div>
                <div>{displayTime.toFixed(3)}s</div>
            </div>
        )

        const childrenRows: JSX.Element[] = []
        if (isGroup && isExpanded) {
            node.children.forEach((child) => {
                childrenRows.push(...renderNode(child, depth + 1))
            })
        }
        return [row, ...childrenRows]
    }

    return (
        <div className="deprecated-space-y-2 p-2 divide-y divide-y-2">
            {rootNodes.flatMap((node) => renderNode(node, 0))}
            {elapsedTime !== undefined && timings.length > 0 ? (
                <div className={clsx('flex justify-between items-start deprecated-space-x-2 py-1.5')}>
                    <div>+ HTTP overhead</div>
                    <div>{(elapsedTime / 1000 - timings[timings.length - 1].t).toFixed(3)}s</div>
                </div>
            ) : null}
        </div>
    )
}

function ElapsedTimeWithTimings({
    elapsedTime,
    hasError,
    timings,
}: {
    elapsedTime: number
    hasError: boolean
    timings: QueryTiming[]
}): JSX.Element | null {
    const [popoverVisible, setPopoverVisible] = useState(false)
    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="bottom"
            overlay={<Timings timings={timings} elapsedTime={elapsedTime} />}
        >
            <div
                onClick={() => setPopoverVisible((visible) => !visible)}
                className={clsx(hasError ? 'text-danger' : '', 'cursor-help')}
            >
                {(elapsedTime / 1000).toFixed(elapsedTime < 1000 ? 2 : 1)}s
            </div>
        </Popover>
    )
}

export function ElapsedTime({ showTimings }: { showTimings?: boolean }): JSX.Element | null {
    const { elapsedTime, loadingStart, responseError, isShowingCachedResults, timings, query } =
        useValues(dataNodeLogic)
    const [, setTick] = useState(0)

    if ('query' in query && query.query === '') {
        return null
    }

    let time = elapsedTime
    if (isShowingCachedResults) {
        time = 0
    }

    if (!isShowingCachedResults && loadingStart && !elapsedTime) {
        time = performance.now() - loadingStart
        window.requestAnimationFrame(() => {
            setTick((tick) => tick + 1)
        })
    }

    if (!time) {
        return null
    }

    if (elapsedTime && timings && showTimings) {
        return <ElapsedTimeWithTimings elapsedTime={elapsedTime} timings={timings} hasError={!!responseError} />
    }

    return <div className={responseError ? 'text-danger' : ''}>{(time / 1000).toFixed(time < 1000 ? 2 : 1)}s</div>
}
