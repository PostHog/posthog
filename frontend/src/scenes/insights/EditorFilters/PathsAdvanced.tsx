import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { AvailableFeature, EditorFilterProps, PathEdgeParameters } from '~/types'

import { PathCleaningFilter } from '../filters/PathCleaningFilter'

export function PathsAdvanced({ insightProps, ...rest }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { edgeLimit, minEdgeWeight, maxEdgeWeight } = pathsFilter || {}

    const [localEdgeParameters, setLocalEdgeParameters] = useState<PathEdgeParameters>({
        edgeLimit,
        minEdgeWeight,
        maxEdgeWeight,
    })

    const updateEdgeParameters = (): void => {
        if (
            localEdgeParameters.edgeLimit !== edgeLimit ||
            localEdgeParameters.minEdgeWeight !== minEdgeWeight ||
            localEdgeParameters.maxEdgeWeight !== maxEdgeWeight
        ) {
            updateInsightFilter({ ...localEdgeParameters })
        }
    }

    return (
        <PayGateMini feature={AvailableFeature.PATHS_ADVANCED}>
            <div className="flex flex-col gap-2">
                <LemonLabel info="Determines the maximum number of path nodes that can be generated. If necessary certain items will be grouped.">
                    Maximum number of paths
                </LemonLabel>
                <LemonInput
                    type="number"
                    min={0}
                    max={1000}
                    defaultValue={localEdgeParameters.edgeLimit || 50}
                    onChange={(value): void =>
                        setLocalEdgeParameters((state) => ({
                            ...state,
                            edgeLimit: Number(value),
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
                <div className="flex items-baseline">
                    <span className="mr-2">Between</span>
                    <LemonInput
                        type="number"
                        min={0}
                        max={100000}
                        defaultValue={localEdgeParameters.minEdgeWeight}
                        onChange={(value): void => {
                            setLocalEdgeParameters((state) => ({
                                ...state,
                                minEdgeWeight: Number(value),
                            }))
                            updateEdgeParameters()
                        }}
                        onBlur={updateEdgeParameters}
                        onPressEnter={updateEdgeParameters}
                    />
                    <span className="mx-2">and</span>
                    <LemonInput
                        type="number"
                        onChange={(value): void => {
                            setLocalEdgeParameters((state) => ({
                                ...state,
                                maxEdgeWeight: Number(value),
                            }))
                            updateEdgeParameters()
                        }}
                        min={0}
                        max={100000}
                        defaultValue={localEdgeParameters.maxEdgeWeight}
                        onBlur={updateEdgeParameters}
                        onPressEnter={updateEdgeParameters}
                    />
                    <span className="ml-2">persons.</span>
                </div>
                <div>
                    <div className="flex items-center my-2">
                        <LemonLabel
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
                    </div>
                    <PathCleaningFilter insightProps={insightProps} {...rest} />
                </div>
            </div>
        </PayGateMini>
    )
}
