import { useActions, useValues } from 'kea'
import React, { useCallback } from 'react'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { LineageNode } from 'products/data_modeling/frontend/lineage/LineageNode'

import { dataModelingLogic } from '../dataModelingLogic'
import type { NodeData } from './types'

const NodeComponent = React.memo(function NodeComponent(props: { id: string; data: NodeData }): JSX.Element {
    const { runNode, materializeNode, setHoveredNodeId } = useActions(dataModelingLogic)
    const { layoutDirection, highlightedNodeIds, debouncedSearchTerm, parsedSearch } = useValues(dataModelingLogic)

    const { id } = props
    const {
        name,
        type,
        handles,
        upstreamCount,
        downstreamCount,
        isRunning,
        isTypeHighlighted,
        lastJobStatus,
        lastRunAt,
        syncInterval,
        userTag,
    } = props.data

    const isSearchMatch = ((): boolean | undefined => {
        if (debouncedSearchTerm.length === 0) {
            return undefined
        }
        if (parsedSearch.mode !== 'search') {
            return highlightedNodeIds(parsedSearch.baseName, parsedSearch.mode).has(id)
        }
        return name.toLowerCase().includes(parsedSearch.baseName.toLowerCase())
    })()

    const handleNodeClick = useCallback((): void => {
        if (type === 'endpoint') {
            const versionMatch = name.match(/^(.+)_v(\d+)$/)
            newInternalTab(
                versionMatch ? urls.endpoint(versionMatch[1], parseInt(versionMatch[2])) : urls.endpoint(name)
            )
        } else {
            newInternalTab(urls.nodeDetail(id))
        }
    }, [type, id, name])

    const canRun = type !== 'table'

    return (
        <LineageNode
            data={{
                node: {
                    id,
                    name,
                    type,
                    sync_interval: syncInterval,
                    last_run_at: lastRunAt,
                    last_run_status: lastJobStatus,
                    upstream_count: upstreamCount,
                    downstream_count: downstreamCount,
                    user_tag: userTag,
                },
                variant: 'canvas',
                direction: layoutDirection,
                state: {
                    isRunning: isRunning ?? false,
                    isHighlighted: (isTypeHighlighted ?? false) || isSearchMatch === true,
                    isDimmed: isSearchMatch === false,
                },
                callbacks: {
                    onClick: handleNodeClick,
                    onMaterialize: type === 'matview' || type === 'endpoint' ? () => materializeNode(id) : undefined,
                    onRunUpstream: canRun ? () => runNode(id, 'upstream') : undefined,
                    onRunDownstream: canRun ? () => runNode(id, 'downstream') : undefined,
                    onMouseEnter: () => setHoveredNodeId(id),
                    onMouseLeave: () => setHoveredNodeId(null),
                },
                handles: handles ?? [],
            }}
        />
    )
})

export const REACT_FLOW_NODE_TYPES = { model: NodeComponent }
