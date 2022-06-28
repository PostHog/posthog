import React from 'react'
import { useValues, useActions } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { BarChartOutlined } from '@ant-design/icons'
import { PathType, FunnelPathType, EditorFilterProps } from '~/types'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { combineUrl, encodeParams, router } from 'kea-router'
import { LemonButton, LemonButtonWithSideAction } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'

export function PathsTargetStart(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="start" {...props} />
}

export function PathsTargetEnd(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="end" {...props} />
}

export function PathsTarget({
    insightProps,
    position,
}: EditorFilterProps & {
    position: 'start' | 'end'
}): JSX.Element {
    const { filter, wildcards } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    const taxonomicGroupTypes: TaxonomicFilterGroupType[] = filter.include_event_types
        ? [
              ...filter.include_event_types.map((item) => {
                  if (item === PathType.Screen) {
                      return TaxonomicFilterGroupType.Screens
                  } else if (item === PathType.CustomEvent) {
                      return TaxonomicFilterGroupType.CustomEvents
                  } else {
                      return TaxonomicFilterGroupType.PageviewUrls
                  }
              }),
              TaxonomicFilterGroupType.Wildcards,
          ]
        : [TaxonomicFilterGroupType.Wildcards]

    const overrideStartInput =
        filter.funnel_paths && [FunnelPathType.between, FunnelPathType.after].includes(filter.funnel_paths)
    const overrideEndInput =
        filter.funnel_paths && [FunnelPathType.between, FunnelPathType.before].includes(filter.funnel_paths)

    const overrideInputs = overrideStartInput || overrideEndInput

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
                <div>
                    <BarChartOutlined />
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
        if (filter.funnel_paths) {
            if (filter.funnel_paths === FunnelPathType.after) {
                return _getStepLabel(filter.funnel_filter, filter.funnel_filter?.funnel_step)
            } else if (filter.funnel_paths === FunnelPathType.between) {
                // funnel_step targets the later of the 2 events when specifying between so the start point index is shifted back 1
                return _getStepLabel(filter.funnel_filter, filter.funnel_filter?.funnel_step, -1)
            } else {
                return <span />
            }
        } else {
            return filter.start_point ? (
                <span className="label">{filter.start_point}</span>
            ) : (
                <span className="label" style={{ color: 'var(--muted)' }}>
                    Add start point
                </span>
            )
        }
    }

    function getEndPointLabel(): JSX.Element {
        if (filter.funnel_paths) {
            if (filter.funnel_paths === FunnelPathType.before || filter.funnel_paths === FunnelPathType.between) {
                return _getStepLabel(filter.funnel_filter, filter.funnel_filter?.funnel_step)
            } else {
                return <span />
            }
        } else {
            return filter.end_point ? (
                <span className="label">{filter.end_point}</span>
            ) : (
                <span className="label" style={{ color: 'var(--muted)' }}>
                    Add end point
                </span>
            )
        }
    }

    const positionOptions = {
        start: {
            index: 0,
            getLabel: getStartPointLabel,
            setFilterKey: 'start_point',
            pathItem: filter.start_point,
            closeButtonEnabled: filter.start_point || overrideStartInput,
            disabled: overrideEndInput && !overrideStartInput,
            funnelFilterLink: filter.funnel_filter && overrideStartInput,
        },
        end: {
            index: 1,
            getLabel: getEndPointLabel,
            setFilterKey: 'end_point',
            pathItem: filter.end_point,
            closeButtonEnabled: filter.end_point || overrideEndInput,
            disabled: overrideStartInput && !overrideEndInput,
            funnelFilterLink: filter.funnel_filter && overrideEndInput,
        },
    }[position]

    const LocalButton = positionOptions.closeButtonEnabled ? LemonButtonWithSideAction : LemonButton

    return (
        <PathItemSelector
            pathItem={positionOptions.pathItem}
            index={positionOptions.index}
            onChange={(pathItem) =>
                setFilter({
                    [positionOptions.setFilterKey]: pathItem,
                })
            }
            taxonomicGroupTypes={taxonomicGroupTypes}
            disabled={overrideInputs}
            wildcardOptions={wildcards}
        >
            <LocalButton
                data-attr={'new-prop-filter-' + positionOptions.index}
                type={positionOptions.funnelFilterLink ? 'secondary' : 'stealth'}
                fullWidth
                outlined
                className="paths-endpoint-field"
                style={{
                    textAlign: 'left',
                    backgroundColor: overrideInputs ? 'var(--border-light)' : 'white',
                }}
                disabled={positionOptions.disabled}
                onClick={
                    positionOptions.funnelFilterLink
                        ? () => {
                              router.actions.push(
                                  combineUrl(
                                      '/insights',
                                      encodeParams(filter.funnel_filter as Record<string, any>, '?')
                                  ).url
                              )
                          }
                        : () => {}
                }
                sideAction={{
                    icon: <IconClose style={{ fontSize: '1rem' }} />,
                    type: 'tertiary',

                    onClick: (e) => {
                        setFilter({
                            [positionOptions.setFilterKey]: undefined,
                            funnel_filter: undefined,
                            funnel_paths: undefined,
                        })
                        e.stopPropagation()
                    },
                }}
            >
                {positionOptions.getLabel()}
            </LocalButton>
        </PathItemSelector>
    )
}
