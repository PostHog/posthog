import React from 'react'
import { Menu, Dropdown } from 'antd'
import { A, combineUrl, encodeParams } from 'kea-router'
import { FunnelPathType, PathType, ViewType } from '~/types'
import { funnelLogic } from './funnelLogic'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelStepDropdown({ index }: { index: number }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { propertiesForUrl: filterProps } = useValues(logic)

    const adjustedIndex = index + 1
    return (
        <div style={{ marginLeft: 10 }}>
            <Dropdown
                overlay={
                    <Menu className="paths-options-dropdown">
                        {adjustedIndex > 1 && (
                            <Menu.Item key="0">
                                <A
                                    href={
                                        combineUrl(
                                            '/insights',
                                            encodeParams(
                                                {
                                                    funnel_filter: { ...filterProps, funnel_step: adjustedIndex },
                                                    insight: ViewType.PATHS,
                                                    funnel_paths: FunnelPathType.before,
                                                    date_from: filterProps.date_from,
                                                    include_event_types: [PathType.PageView, PathType.CustomEvent],
                                                },
                                                '?'
                                            )
                                        ).url
                                    }
                                >
                                    Show user paths leading to step
                                </A>
                            </Menu.Item>
                        )}
                        {adjustedIndex > 1 && (
                            <Menu.Item key="1">
                                <A
                                    href={
                                        combineUrl(
                                            '/insights',
                                            encodeParams(
                                                {
                                                    funnel_filter: { ...filterProps, funnel_step: adjustedIndex },
                                                    insight: ViewType.PATHS,
                                                    funnel_paths: FunnelPathType.between,
                                                    date_from: filterProps.date_from,
                                                    include_event_types: [PathType.PageView, PathType.CustomEvent],
                                                },
                                                '?'
                                            )
                                        ).url
                                    }
                                >
                                    Show user paths between previous step and this step
                                </A>
                            </Menu.Item>
                        )}
                        <Menu.Item key="2">
                            <A
                                href={
                                    combineUrl(
                                        '/insights',
                                        encodeParams(
                                            {
                                                funnel_filter: { ...filterProps, funnel_step: adjustedIndex },
                                                insight: ViewType.PATHS,
                                                funnel_paths: FunnelPathType.after,
                                                date_from: filterProps.date_from,
                                                include_event_types: [PathType.PageView, PathType.CustomEvent],
                                            },
                                            '?'
                                        )
                                    ).url
                                }
                            >
                                Show user paths after step
                            </A>
                        </Menu.Item>
                        {adjustedIndex > 1 && (
                            <Menu.Item key="3">
                                <A
                                    href={
                                        combineUrl(
                                            '/insights',
                                            encodeParams(
                                                {
                                                    funnel_filter: { ...filterProps, funnel_step: adjustedIndex * -1 },
                                                    insight: ViewType.PATHS,
                                                    funnel_paths: FunnelPathType.after,
                                                    date_from: filterProps.date_from,
                                                    include_event_types: [PathType.PageView, PathType.CustomEvent],
                                                },
                                                '?'
                                            )
                                        ).url
                                    }
                                >
                                    Show user paths after dropoff
                                </A>
                            </Menu.Item>
                        )}
                        {adjustedIndex > 1 && (
                            <Menu.Item key="3">
                                <A
                                    href={
                                        combineUrl(
                                            '/insights',
                                            encodeParams(
                                                {
                                                    funnel_filter: { ...filterProps, funnel_step: adjustedIndex * -1 },
                                                    insight: ViewType.PATHS,
                                                    funnel_paths: FunnelPathType.before,
                                                    date_from: filterProps.date_from,
                                                    include_event_types: [PathType.PageView, PathType.CustomEvent],
                                                },
                                                '?'
                                            )
                                        ).url
                                    }
                                >
                                    Show user paths before dropoff
                                </A>
                            </Menu.Item>
                        )}
                    </Menu>
                }
                trigger={['click']}
            >
                <div className="paths-dropdown-ellipsis">...</div>
            </Dropdown>
        </div>
    )
}
