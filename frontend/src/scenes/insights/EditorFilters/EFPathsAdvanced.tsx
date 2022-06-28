import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { EditorFilterProps, PathEdgeParameters } from '~/types'
import { InfoCircleOutlined, SettingOutlined } from '@ant-design/icons'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { InputNumber, Tooltip } from 'antd'
import { Link } from 'lib/components/Link'
import { PathCleaningFilter } from '../filters/PathCleaningFilter'

export function EFPathsAdvanced({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))
    const [localEdgeParameters, setLocalEdgeParameters] = useState<PathEdgeParameters>({
        edge_limit: filter.edge_limit,
        min_edge_weight: filter.min_edge_weight,
        max_edge_weight: filter.max_edge_weight,
    })

    const updateEdgeParameters = (): void => {
        if (
            localEdgeParameters.edge_limit !== filter.edge_limit ||
            localEdgeParameters.min_edge_weight !== filter.min_edge_weight ||
            localEdgeParameters.max_edge_weight !== filter.max_edge_weight
        ) {
            setFilter({ ...localEdgeParameters })
        }
    }

    return (
        <div>
            <div className="mb-05">
                <b>Maximum number of paths</b>
                <Tooltip title="Determines the maximum number of path nodes that can be generated. If necessary certain items will be grouped.">
                    <InfoCircleOutlined className="info-indicator" style={{ marginRight: 4 }} />
                </Tooltip>
            </div>
            <InputNumber
                style={{
                    marginBottom: 16,
                }}
                min={0}
                max={1000}
                defaultValue={50}
                onChange={(value): void =>
                    setLocalEdgeParameters((state) => ({
                        ...state,
                        edge_limit: Number(value),
                    }))
                }
                onBlur={updateEdgeParameters}
                onPressEnter={updateEdgeParameters}
            />
            <div className="mb-05">
                <b>Number of people on each path</b>
                <Tooltip title="Determines the minimum and maximum number of persons in each path. Helps adjust the density of the visualization.">
                    <InfoCircleOutlined className="info-indicator" style={{ marginRight: 4 }} />
                </Tooltip>
            </div>
            <div>
                between{' '}
                <InputNumber
                    style={{
                        marginBottom: 16,
                    }}
                    min={0}
                    max={100000}
                    onChange={(value): void =>
                        setLocalEdgeParameters((state) => ({
                            ...state,
                            min_edge_weight: Number(value),
                        }))
                    }
                    onBlur={updateEdgeParameters}
                    onPressEnter={updateEdgeParameters}
                />{' '}
                and{' '}
                <InputNumber
                    style={{
                        marginBottom: 16,
                    }}
                    onChange={(value): void =>
                        setLocalEdgeParameters((state) => ({
                            ...state,
                            max_edge_weight: Number(value),
                        }))
                    }
                    min={0}
                    max={100000}
                    onBlur={updateEdgeParameters}
                    onPressEnter={updateEdgeParameters}
                />
            </div>
            <div className="mb-05">
                <div style={{ display: 'flex' }}>
                    <b>
                        Path Cleaning Rules: (optional){' '}
                        <Tooltip
                            title={
                                <>
                                    Cleaning rules are an advanced feature that uses regex to normalize URLS for paths
                                    visualization. Rules can be set for all insights in the project settings, or they
                                    can be defined specifically for an insight.
                                </>
                            }
                        >
                            <InfoCircleOutlined className="info-indicator" style={{ marginRight: 4 }} />
                        </Tooltip>
                    </b>
                    <Link style={{ flexGrow: 1, textAlign: 'right' }} to="/project/settings#path_cleaning_filtering">
                        <SettingOutlined /> Configure Project Rules
                    </Link>
                </div>
            </div>
            <PathCleaningFilter />
        </div>
    )
}
