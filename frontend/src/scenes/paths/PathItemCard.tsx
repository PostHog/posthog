import { useActions, useValues } from 'kea'
import { Button, Menu, Dropdown, Tooltip, Row } from 'antd'
import { ClockCircleOutlined } from '@ant-design/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, InsightLogicProps } from '~/types'
import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/components/icons'
import { humanFriendlyDuration, copyToClipboard } from 'lib/utils'

import { pageUrl, getContinuingValue, getDropOffValue, isSelectedPathStartOrEnd, PathNodeData } from './pathUtils'
import { pathsLogic } from './pathsLogic'

import './PathItemCard.scss'

type PathItemCardProps = {
    node: PathNodeData
    insightProps: InsightLogicProps
}

export function PathItemCard({ node, insightProps }: PathItemCardProps): JSX.Element | null {
    const { filter } = useValues(pathsLogic(insightProps))
    const { openPersonsModal, setFilter, viewPathToFunnel } = useActions(pathsLogic(insightProps))

    const { user } = useValues(userLogic)
    const hasAdvancedPaths = user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)

    const continuingValue = getContinuingValue(node.sourceLinks)
    const dropOffValue = getDropOffValue(node)

    if (!node.visible) {
        return null
    }

    return (
        <Tooltip title={pageUrl(node)} placement="right" className="PathItemCard">
            <Dropdown
                overlay={
                    <Menu
                        style={{
                            marginTop: -5,
                            border: '1px solid var(--border)',
                            borderRadius: '0px 0px 4px 4px',
                            width: 200,
                        }}
                    >
                        {node.sourceLinks.length > 0 && (
                            <div className="text-xs flex items-center p-2 gap-2">
                                <IconTrendingFlat className="text-xl shrink-0 text-success" />
                                <span>Continuing</span>

                                <LemonButton
                                    size="small"
                                    onClick={() => openPersonsModal({ path_start_key: node.name })}
                                >
                                    <span className="text-xs">
                                        {continuingValue}
                                        <span className="text-muted-alt ml-2">
                                            ({((continuingValue / node.value) * 100).toFixed(1)}
                                            %)
                                        </span>
                                    </span>
                                </LemonButton>
                            </div>
                        )}
                        {dropOffValue > 0 && (
                            <div className="text-xs flex items-center p-2 gap-2 border-t">
                                <IconTrendingFlatDown className="text-xl shrink-0 text-danger" />
                                <span>Dropping off</span>
                                <LemonButton
                                    size="small"
                                    onClick={() =>
                                        openPersonsModal({
                                            path_dropoff_key: node.name,
                                        })
                                    }
                                >
                                    <span className="text-xs">
                                        {dropOffValue}
                                        <span className="text-muted-alt text-xs ml-2">
                                            ({((dropOffValue / node.value) * 100).toFixed(1)}
                                            %)
                                        </span>
                                    </span>
                                </LemonButton>
                            </div>
                        )}
                        {node.targetLinks.length > 0 && (
                            <div className="text-xs flex items-center p-2 gap-2 border-t">
                                <ClockCircleOutlined style={{ color: 'var(--muted)', fontSize: 16 }} />
                                <span>
                                    Average time from previous step{' '}
                                    <b>{humanFriendlyDuration(node.targetLinks[0].average_conversion_time / 1000)}</b>
                                </span>
                            </div>
                        )}
                    </Menu>
                }
                placement="bottomCenter"
            >
                <Button
                    className="absolute flex justify-between items-center bg-white p-1 "
                    style={{
                        width: 200,
                        left: node.sourceLinks.length === 0 ? node.x0 - (200 - 7) : node.x0 + 7,
                        top: node.sourceLinks.length > 0 ? node.y0 + 5 : node.y0 + (node.y1 - node.y0) / 2,
                        border: `1px solid ${isSelectedPathStartOrEnd(filter, node) ? 'purple' : 'var(--border)'}`,
                    }}
                >
                    <div className="flex items-center font-semibold">
                        <span className="text-xxs text-muted mr-1">{`0${node.name[0]}`}</span>
                        <span className="text-xs">{pageUrl(node, true)}</span>
                    </div>
                    <Row>
                        <span
                            className="text-primary text-xs self-center pr-1 font-medium"
                            onClick={() => openPersonsModal({ path_end_key: node.name })}
                        >
                            {continuingValue + dropOffValue}
                        </span>
                        <Dropdown
                            trigger={['click']}
                            overlay={
                                <Menu className="paths-options-dropdown">
                                    <Menu.Item onClick={() => setFilter({ start_point: pageUrl(node) })}>
                                        Set as path start
                                    </Menu.Item>
                                    {hasAdvancedPaths && (
                                        <>
                                            <Menu.Item
                                                onClick={() =>
                                                    setFilter({
                                                        end_point: pageUrl(node),
                                                    })
                                                }
                                            >
                                                Set as path end
                                            </Menu.Item>
                                            <Menu.Item
                                                onClick={() => {
                                                    setFilter({
                                                        exclude_events: [
                                                            ...(filter.exclude_events || []),
                                                            pageUrl(node, false),
                                                        ],
                                                    })
                                                }}
                                            >
                                                Exclude path item
                                            </Menu.Item>

                                            <Menu.Item onClick={() => viewPathToFunnel(node)}>View funnel</Menu.Item>
                                        </>
                                    )}
                                    <Menu.Item onClick={() => copyToClipboard(pageUrl(node))}>
                                        Copy path item name
                                    </Menu.Item>
                                </Menu>
                            }
                        >
                            <div className="paths-dropdown-ellipsis">...</div>
                        </Dropdown>
                    </Row>
                </Button>
            </Dropdown>
        </Tooltip>
    )
}
