import { useActions, useValues } from 'kea'
import { combineUrl, encodeParams, router } from 'kea-router'
import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { IconClose, IconFunnelVertical } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

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
    const { pathsFilter, taxonomicGroupTypes } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const { funnelPaths, funnelFilter, startPoint, endPoint, pathGroupings } = pathsFilter || {}

    const overrideStartInput = funnelPaths && [FunnelPathType.between, FunnelPathType.after].includes(funnelPaths)
    const overrideEndInput = funnelPaths && [FunnelPathType.between, FunnelPathType.before].includes(funnelPaths)
    const overrideInputs = overrideStartInput || overrideEndInput

    const key = position === 'start' ? 'startPoint' : 'endPoint'
    const onChange = (item: string): void => {
        updateInsightFilter({ [key]: item })
    }
    const onReset = (): void => {
        updateInsightFilter({ [key]: undefined, funnelFilter: undefined, funnelPaths: undefined })
    }

    function _getStepNameAtIndex(filters: Record<string, any>, index: number): string {
        const targetEntity =
            filters.events?.filter((event: Record<string, any>) => {
                return event.order === index - 1
            })?.[0] ||
            filters.actions?.filter((action: Record<string, any>) => {
                return action.order === index - 1
            })?.[0]

        return targetEntity?.name || ''
    }

    function _getStepLabel(funnelFilters?: Record<string, any>, index?: number, shift: number = 0): JSX.Element {
        if (funnelFilters && index) {
            return (
                <div className="flex items-center gap-2">
                    <IconFunnelVertical className="text-2xl" />
                    <span className="label">{`${
                        index > 0 ? 'Funnel step ' + (index + shift) : 'Funnel dropoff ' + index * -1
                    }: ${_getStepNameAtIndex(funnelFilters, index > 0 ? index + shift : index * -1)}`}</span>
                </div>
            )
        } else {
            return <span />
        }
    }

    function getStartPointLabel(): JSX.Element {
        if (funnelPaths) {
            if (funnelPaths === FunnelPathType.after) {
                return _getStepLabel(funnelFilter, funnelFilter?.funnel_step)
            } else if (funnelPaths === FunnelPathType.between) {
                // funnel_step targets the later of the 2 events when specifying between so the start point index is shifted back 1
                return _getStepLabel(funnelFilter, funnelFilter?.funnel_step, -1)
            } else {
                return <span />
            }
        } else {
            return startPoint ? (
                <span className="label">{startPoint}</span>
            ) : (
                <span className="label text-muted">Add start point</span>
            )
        }
    }

    function getEndPointLabel(): JSX.Element {
        if (funnelPaths) {
            if (funnelPaths === FunnelPathType.before || funnelPaths === FunnelPathType.between) {
                return _getStepLabel(funnelFilter, funnelFilter?.funnel_step)
            } else {
                return <span />
            }
        } else {
            return endPoint ? (
                <span className="label">{endPoint}</span>
            ) : (
                <span className="label text-muted">Add end point</span>
            )
        }
    }

    const positionOptions = {
        start: {
            index: 0,
            getLabel: getStartPointLabel,
            pathItem: startPoint,
            closeButtonEnabled: startPoint || overrideStartInput,
            disabled: overrideEndInput && !overrideStartInput,
            funnelFilterLink: funnelFilter && overrideStartInput,
        },
        end: {
            index: 1,
            getLabel: getEndPointLabel,
            pathItem: endPoint,
            closeButtonEnabled: endPoint || overrideEndInput,
            disabled: overrideStartInput && !overrideEndInput,
            funnelFilterLink: funnelFilter && overrideEndInput,
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
                                  combineUrl('/insights', encodeParams(funnelFilter as Record<string, any>, '?')).url
                              )
                          }
                        : () => {}
                }
                sideAction={
                    positionOptions.closeButtonEnabled
                        ? {
                              icon: <IconClose />,
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
