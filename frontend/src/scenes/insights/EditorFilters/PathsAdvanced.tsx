import { LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { IconSettings } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { Link } from 'lib/lemon-ui/Link'
import { useState } from 'react'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature, EditorFilterProps, PathEdgeParameters } from '~/types'

import { PathCleaningFilter } from '../filters/PathCleaningFilter'

export function PathsAdvanced({ insightProps, ...rest }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { edge_limit, min_edge_weight, max_edge_weight } = pathsFilter || {}

    const [localEdgeParameters, setLocalEdgeParameters] = useState<PathEdgeParameters>({
        edge_limit: edge_limit,
        min_edge_weight: min_edge_weight,
        max_edge_weight: max_edge_weight,
    })

    const updateEdgeParameters = (): void => {
        if (
            localEdgeParameters.edge_limit !== edge_limit ||
            localEdgeParameters.min_edge_weight !== min_edge_weight ||
            localEdgeParameters.max_edge_weight !== max_edge_weight
        ) {
            updateInsightFilter({ ...localEdgeParameters })
        }
    }

    return (
        <PayGateMini feature={AvailableFeature.PATHS_ADVANCED}>
            <div className="flex flex-col gap-2">
                <LemonDivider />
                <LemonLabel info="Determines the maximum number of path nodes that can be generated. If necessary certain items will be grouped.">
                    Maximum number of paths
                </LemonLabel>
                <LemonInput
                    type="number"
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
                <LemonLabel
                    info="Determines the minimum and maximum number of persons in each path. Helps adjust the density of the visualization."
                    className="mt-2"
                >
                    Number of people on each path
                </LemonLabel>
                <div>
                    <span className="mr-2">Between</span>
                    <LemonInput
                        type="number"
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
                    />
                    <span className="mx-2">and</span>
                    <LemonInput
                        type="number"
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
                    <span className="ml-2">persons.</span>
                </div>
                <div>
                    <div className="flex items-center my-2">
                        <LemonLabel
                            showOptional
                            info={
                                <>
                                    Cleaning rules are an advanced feature that uses regex to normalize URLS for paths
                                    visualization. Rules can be set for all insights in the project settings, or they
                                    can be defined specifically for an insight.
                                </>
                            }
                        >
                            Path Cleaning Rules
                        </LemonLabel>
                        <Link
                            className="flex items-center ml-2"
                            to={urls.settings('project-product-analytics', 'path-cleaning')}
                        >
                            <IconSettings fontSize="16" className="mr-0.5" />
                            Configure Project Rules
                        </Link>
                    </div>
                    <PathCleaningFilter insightProps={insightProps} {...rest} />
                </div>
            </div>
        </PayGateMini>
    )
}
