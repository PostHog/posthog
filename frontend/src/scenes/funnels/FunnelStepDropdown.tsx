import React from 'react'
import { Menu, Dropdown } from 'antd'
import { EllipsisOutlined } from '@ant-design/icons'
import { A, combineUrl, encodeParams } from 'kea-router'
import { FilterType, FunnelPathType, ViewType } from '~/types'

export function FunnelStepDropdown({ filterProps, index }: { filterProps: FilterType; index: number }): JSX.Element {
    const adjustedIndex = index + 1
    return (
        <div style={{ marginLeft: 10 }}>
            <Dropdown
                overlay={
                    <Menu>
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
                <EllipsisOutlined />
            </Dropdown>
        </div>
    )
}
