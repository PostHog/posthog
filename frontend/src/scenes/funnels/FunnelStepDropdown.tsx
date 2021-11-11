import React from 'react'
import { Menu, Dropdown } from 'antd'
import { A, combineUrl, encodeParams } from 'kea-router'
import { FunnelPathType, PathType, InsightType, AvailableFeature } from '~/types'
import { funnelLogic } from './funnelLogic'
import { useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

export function FunnelStepDropdown({ index }: { index: number }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { propertiesForUrl: filterProps, filters } = useValues(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)

    if (!featureFlags[FEATURE_FLAGS.NEW_PATHS_UI]) {
        return null
    }

    if (!user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)) {
        // TODO: Consider showing the options but disabled with a prompt to upgrade
        return null
    }

    // Don't show paths modal if aggregating by groups - paths is user-based!
    if (filters.aggregation_group_type_index != undefined) {
        return null
    }

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
                                                    insight: InsightType.PATHS,
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
                                                    insight: InsightType.PATHS,
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
                                                insight: InsightType.PATHS,
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
                                                    insight: InsightType.PATHS,
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
                                                    insight: InsightType.PATHS,
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
