import { useState } from 'react'
import { useActions, useValues } from 'kea'
import { EditorFilterProps, PathEdgeParameters } from '~/types'

import { pathsLogic } from 'scenes/paths/pathsLogic'
import { InputNumber } from 'antd'
import { Link } from 'lib/components/Link'
import { PathCleaningFilter } from '../filters/PathCleaningFilter'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { IconSettings } from 'lib/components/icons'

export function PathsAdvanced({ insightProps }: EditorFilterProps): JSX.Element {
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
        <div className="flex flex-col gap-2">
            <LemonLabel info="Determines the maximum number of path nodes that can be generated. If necessary certain items will be grouped.">
                Maximum number of paths
            </LemonLabel>
            <InputNumber
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
            <LemonLabel info="Determines the minimum and maximum number of persons in each path. Helps adjust the density of the visualization.">
                Number of people on each path
            </LemonLabel>
            <div>
                between{' '}
                <InputNumber
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
            <div>
                <div className="flex mb-2">
                    <LemonLabel
                        showOptional
                        info={
                            <>
                                Cleaning rules are an advanced feature that uses regex to normalize URLS for paths
                                visualization. Rules can be set for all insights in the project settings, or they can be
                                defined specifically for an insight.
                            </>
                        }
                    >
                        Path Cleaning Rules
                    </LemonLabel>
                    <Link className="grow-1 text-right" to="/project/settings#path_cleaning_filtering">
                        <IconSettings /> Configure Project Rules
                    </Link>
                </div>
                <PathCleaningFilter />
            </div>
        </div>
    )
}
