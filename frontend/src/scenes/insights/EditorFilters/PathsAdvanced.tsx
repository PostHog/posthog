import { useState } from 'react'
import { useActions, useValues } from 'kea'
import { InputNumber } from 'antd'

import { EditorFilterProps, PathEdgeParameters, PathsFilterType, QueryEditorFilterProps } from '~/types'
import { LemonDivider } from '@posthog/lemon-ui'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { Link } from 'lib/components/Link'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { IconSettings } from 'lib/components/icons'

import { PathCleaningFilter, PathCleaningFilterDataExploration } from '../filters/PathCleaningFilter'

export function PathsAdvancedDataExploration({ insightProps, ...rest }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    return (
        <PathsAdvancedComponent
            setFilter={updateInsightFilter}
            cleaningFilterComponent={<PathCleaningFilterDataExploration insightProps={insightProps} {...rest} />}
            {...insightFilter}
        />
    )
}

export function PathsAdvanced({ insightProps, ...rest }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return (
        <PathsAdvancedComponent
            setFilter={setFilter}
            cleaningFilterComponent={<PathCleaningFilter insightProps={insightProps} {...rest} />}
            {...filter}
        />
    )
}

type PathsAdvancedComponentProps = {
    setFilter: (filter: PathsFilterType) => void
    cleaningFilterComponent: JSX.Element
} & PathsFilterType

export function PathsAdvancedComponent({
    setFilter,
    edge_limit,
    min_edge_weight,
    max_edge_weight,
    cleaningFilterComponent,
}: PathsAdvancedComponentProps): JSX.Element {
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
            setFilter({ ...localEdgeParameters })
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonDivider />
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
            <LemonLabel
                info="Determines the minimum and maximum number of persons in each path. Helps adjust the density of the visualization."
                className="mt-2"
            >
                Number of people on each path
            </LemonLabel>
            <div>
                <span className="mr-2">Between</span>
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
                />
                <span className="mx-2">and</span>
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
                <span className="ml-2">persons.</span>
            </div>
            <div>
                <div className="flex items-center justify-between my-2">
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
                    <Link className="flex items-center" to="/project/settings#path_cleaning_filtering">
                        Configure Project Rules
                        <IconSettings fontSize="16" className="ml-0.5" />
                    </Link>
                </div>
                {cleaningFilterComponent}
            </div>
        </div>
    )
}
