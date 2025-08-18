import { useActions, useValues } from 'kea'
import { combineUrl, encodeParams, router } from 'kea-router'

import { IconX } from '@posthog/icons'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconFunnelVertical } from 'lib/lemon-ui/icons'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelsQuery, PathsQuery } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelPathType } from '~/types'

export function PathsTargetStart(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="start" {...props} />
}

export function PathsTargetEnd(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="end" {...props} />
}

type PathTargetProps = {
    position: 'start' | 'end'
} & EditorFilterProps

function PathsTarget({ position, insightProps }: PathTargetProps): JSX.Element {
    const { pathsFilter, funnelPathsFilter, taxonomicGroupTypes } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter, updateQuerySource } = useActions(pathsDataLogic(insightProps))

    const { startPoint, endPoint, pathGroupings } = pathsFilter || {}
    const { funnelPathType, funnelSource, funnelStep } = funnelPathsFilter || {}

    const overrideStartInput = funnelPathType && [FunnelPathType.between, FunnelPathType.after].includes(funnelPathType)
    const overrideEndInput = funnelPathType && [FunnelPathType.between, FunnelPathType.before].includes(funnelPathType)
    const overrideInputs = overrideStartInput || overrideEndInput

    const key = position === 'start' ? 'startPoint' : 'endPoint'
    const onChange = (item: string): void => {
        updateInsightFilter({ [key]: item })
    }
    const onReset = (): void => {
        updateQuerySource({
            pathsFilter: { ...pathsFilter, [key]: undefined },
            funnelPathsFilter: undefined,
        } as Partial<PathsQuery>)
    }

    function _getStepNameAtIndex(filters: FunnelsQuery, index: number): string {
        return filters.series[index - 1].name ?? ''
    }

    function _getStepLabel(funnelSource?: FunnelsQuery, index?: number, shift: number = 0): JSX.Element {
        if (funnelSource && index) {
            return (
                <div className="flex items-center gap-2">
                    <IconFunnelVertical className="text-2xl" />
                    <span className="label">{`${
                        index > 0 ? 'Funnel step ' + (index + shift) : 'Funnel dropoff ' + index * -1
                    }: ${_getStepNameAtIndex(funnelSource, index > 0 ? index + shift : index * -1)}`}</span>
                </div>
            )
        }
        return <span />
    }

    function getStartPointLabel(): JSX.Element {
        if (funnelPathType) {
            if (funnelPathType === FunnelPathType.after) {
                return _getStepLabel(funnelSource, funnelStep)
            } else if (funnelPathType === FunnelPathType.between) {
                // funnel_step targets the later of the 2 events when specifying between so the start point index is shifted back 1
                return _getStepLabel(funnelSource, funnelStep, -1)
            }
            return <span />
        }
        return startPoint ? (
            <span className="label">{startPoint}</span>
        ) : (
            <span className="label text-secondary">Add start point</span>
        )
    }

    function getEndPointLabel(): JSX.Element {
        if (funnelPathType) {
            if (funnelPathType === FunnelPathType.before || funnelPathType === FunnelPathType.between) {
                return _getStepLabel(funnelSource, funnelStep)
            }
            return <span />
        }
        return endPoint ? (
            <span className="label">{endPoint}</span>
        ) : (
            <span className="label text-secondary">Add end point</span>
        )
    }

    const positionOptions = {
        start: {
            index: 0,
            getLabel: getStartPointLabel,
            pathItem: startPoint,
            closeButtonEnabled: startPoint || overrideStartInput,
            disabled: overrideEndInput && !overrideStartInput,
            funnelFilterLink: funnelSource && overrideStartInput,
        },
        end: {
            index: 1,
            getLabel: getEndPointLabel,
            pathItem: endPoint,
            closeButtonEnabled: endPoint || overrideEndInput,
            disabled: overrideStartInput && !overrideEndInput,
            funnelFilterLink: funnelSource && overrideEndInput,
        },
    }[position]

    return (
        <PathItemSelector
            pathItem={positionOptions.pathItem}
            index={positionOptions.index}
            onChange={onChange}
            taxonomicGroupTypes={taxonomicGroupTypes}
            disabled={overrideInputs}
            wildcardOptions={pathGroupings?.map((name) => ({ name }))}
        >
            <LemonButton
                data-attr={'new-prop-filter-' + positionOptions.index}
                fullWidth
                className="paths-endpoint-field"
                type="secondary"
                active={overrideInputs}
                disabled={positionOptions.disabled}
                onClick={
                    positionOptions.funnelFilterLink
                        ? () => {
                              router.actions.push(
                                  combineUrl(
                                      '/insights',
                                      encodeParams(queryNodeToFilter(funnelSource as FunnelsQuery), '?')
                                  ).url
                              )
                          }
                        : () => {}
                }
                sideAction={
                    positionOptions.closeButtonEnabled
                        ? {
                              icon: <IconX />,
                              type: 'tertiary',
                              onClick: (e) => {
                                  onReset()
                                  e.stopPropagation()
                              },
                          }
                        : null
                }
            >
                {positionOptions.getLabel()}
            </LemonButton>
        </PathItemSelector>
    )
}
