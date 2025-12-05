import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightLogicProps } from '~/types'

import { PathNodeData, pageUrl } from './pathUtils'
import { pathsDataLogic } from './pathsDataLogic'
import { NODE_LABEL_HEIGHT, NODE_LABEL_LEFT_OFFSET, NODE_LABEL_TOP_OFFSET, NODE_LABEL_WIDTH } from './renderPaths'

export type PathNodeLabelProps = {
    insightProps: InsightLogicProps
    node: PathNodeData
}

export function PathNodeLabel({ insightProps, node }: PathNodeLabelProps): JSX.Element | null {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter, openPersonsModal, viewPathToFunnel } = useActions(pathsDataLogic(insightProps))

    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    const nodeName = pageUrl(node)
    const isPath = nodeName.includes('/')

    const setAsPathStart = (): void => updateInsightFilter({ startPoint: nodeName })
    const setAsPathEnd = (): void => updateInsightFilter({ endPoint: nodeName })
    const excludePathItem = (): void => {
        updateInsightFilter({ excludeEvents: [...(pathsFilter?.excludeEvents || []), pageUrl(node, false)] })
    }
    const viewFunnel = (): void => {
        viewPathToFunnel(node)
    }
    const copyName = (): void => {
        void copyToClipboard(nodeName).catch((e) => posthog.captureException(e))
    }
    const openModal = (): void => openPersonsModal({ path_end_key: node.name })

    const isTruncatedPath = node.name.slice(1) === '_...'

    return (
        <div
            className="absolute"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_LABEL_WIDTH,
                height: NODE_LABEL_HEIGHT,
                left: node.x0 + NODE_LABEL_LEFT_OFFSET,
                top: node.y0 + NODE_LABEL_TOP_OFFSET,
            }}
        >
            <div className="flex items-center">
                <Tooltip title={pageUrl(node)} placement="right">
                    <div className="font-semibold overflow-hidden max-h-16 text-xs break-words">
                        {pageUrl(node, isPath)}
                    </div>
                </Tooltip>
                {!isTruncatedPath && (
                    <LemonMenu
                        items={[
                            { label: 'Set as path start', onClick: setAsPathStart },
                            ...(hasAdvancedPaths
                                ? [
                                      { label: 'Set as path end', onClick: setAsPathEnd },
                                      { label: 'Exclude path item', onClick: excludePathItem },
                                      {
                                          label: (
                                              <div className="flex justify-between items-center w-full">
                                                  <span>View funnel</span>
                                                  <IconOpenInNew />
                                              </div>
                                          ),
                                          onClick: viewFunnel,
                                      },
                                  ]
                                : []),
                            { label: 'Copy path item name', onClick: copyName },
                        ]}
                    >
                        <IconEllipsis className="ml-1 cursor-pointer text-muted hover:text-default" />
                    </LemonMenu>
                )}
            </div>

            <LemonButton size="xsmall" onClick={openModal} noPadding>
                <span className="font-normal">{node.value}</span>
            </LemonButton>
        </div>
    )
}
