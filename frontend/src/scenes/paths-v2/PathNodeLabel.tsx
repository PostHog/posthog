import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, PopoverReferenceContext, Tooltip } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import { useActions, useValues } from 'kea'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { FunnelPathsFilter } from '~/queries/schema'
import { AvailableFeature, InsightLogicProps } from '~/types'

import { pathsDataLogic } from './pathsDataLogic'
import { isSelectedPathStartOrEnd, pageUrl, PathNodeData } from './pathUtils'
import { NODE_LABEL_HEIGHT, NODE_LABEL_LEFT_OFFSET, NODE_LABEL_TOP_OFFSET, NODE_LABEL_WIDTH } from './renderPaths'

export type PathNodeLabelProps = {
    insightProps: InsightLogicProps
    node: PathNodeData
}

export function PathNodeLabel({ insightProps, node }: PathNodeLabelProps): JSX.Element | null {
    const { pathsFilter: _pathsFilter, funnelPathsFilter: _funnelPathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter, openPersonsModal, viewPathToFunnel } = useActions(pathsDataLogic(insightProps))

    const pathsFilter = _pathsFilter || {}
    const funnelPathsFilter = _funnelPathsFilter || ({} as FunnelPathsFilter)

    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    const nodeName = pageUrl(node)
    const isPath = nodeName.includes('/')

    const setAsPathStart = (): void => updateInsightFilter({ startPoint: nodeName })
    const setAsPathEnd = (): void => updateInsightFilter({ endPoint: nodeName })
    const excludePathItem = (): void => {
        updateInsightFilter({ excludeEvents: [...(pathsFilter.excludeEvents || []), pageUrl(node, false)] })
    }
    const viewFunnel = (): void => {
        viewPathToFunnel(node)
    }
    const copyName = (): void => {
        void copyToClipboard(nodeName).then(captureException)
    }
    const openModal = (): void => openPersonsModal({ path_end_key: node.name })

    const isTruncatedPath = node.name.slice(1) === '_...'

    return (
        <Tooltip title={pageUrl(node)} placement="right">
            <div
                className="absolute rounded bg-bg-light p-1"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: NODE_LABEL_WIDTH,
                    height: NODE_LABEL_HEIGHT,
                    left: node.x0 + NODE_LABEL_LEFT_OFFSET,
                    top: node.y0 + NODE_LABEL_TOP_OFFSET,
                    border: `1px solid ${
                        isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, node) ? 'purple' : 'var(--border)'
                    }`,
                }}
            >
                <div className="flex justify-between items-center w-full">
                    <div className="font-semibold overflow-hidden max-h-16">
                        <span className="text-xs break-words">{pageUrl(node, isPath)}</span>
                    </div>
                    {/* TRICKY: We don't want the popover to affect the buttons */}
                    <PopoverReferenceContext.Provider value={null}>
                        <div className="flex flex-nowrap">
                            <LemonButton size="small" onClick={openModal}>
                                <span className="text-link text-xs px-1 font-medium">{node.value}</span>
                            </LemonButton>
                            <LemonMenu
                                items={[
                                    { label: 'Set as path start', onClick: setAsPathStart },
                                    ...(hasAdvancedPaths
                                        ? [
                                              { label: 'Set as path end', onClick: setAsPathEnd },
                                              { label: 'Exclude path item', onClick: excludePathItem },
                                              { label: 'View funnel', onClick: viewFunnel },
                                          ]
                                        : []),
                                    { label: 'Copy path item name', onClick: copyName },
                                ]}
                                placement="bottom-end"
                            >
                                <LemonButton
                                    size="small"
                                    icon={<IconEllipsis />}
                                    disabledReason={
                                        isTruncatedPath
                                            ? 'Multiple paths truncated and combined for efficiency during querying. No further analysis possible.'
                                            : undefined
                                    }
                                />
                            </LemonMenu>
                        </div>
                    </PopoverReferenceContext.Provider>
                </div>
            </div>
        </Tooltip>
    )
}
