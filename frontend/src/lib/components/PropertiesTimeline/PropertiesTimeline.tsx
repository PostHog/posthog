import { Properties } from '@posthog/plugin-scaffold'
import { dayjsUtcToTimezone } from 'lib/dayjs'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { useActions, useValues } from 'kea'
import { LemonDivider } from '@posthog/lemon-ui'
import { propertiesTimelineLogic, PropertiesTimelineProps } from './propertiesTimelineLogic'
import { TimelineSeekbar } from '../TimelineSeekbar'
import { Tooltip } from '../Tooltip'
import { IconInfo } from '../icons'
import { humanList } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

export function PropertiesTimeline({ actor, filter }: PropertiesTimelineProps): JSX.Element {
    const logic = propertiesTimelineLogic({ actor, filter })
    const { points, crucialPropertyKeys, resultLoading, selectedPointIndex, timezone } = useValues(logic)
    const { setSelectedPointIndex } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)

    if (currentTeam && !currentTeam.person_on_events_querying_enabled) {
        throw new Error('Properties timeline is irrelevant if persons-on-events querying is disabled')
    }

    const propertiesShown: Properties =
        points.length > 0 && selectedPointIndex !== null ? points[selectedPointIndex].properties : actor.properties

    return (
        <div className="flex flex-col px-2">
            <TimelineSeekbar
                points={
                    points
                        ? points.map(({ timestamp, relevantEventCount }) => ({
                              timestamp,
                              count: relevantEventCount,
                          }))
                        : []
                }
                note={
                    <>
                        <span>{crucialPropertyKeys.length > 0 ? 'Relevant properties' : 'Properties'} over time</span>
                        {!resultLoading && (
                            <Tooltip
                                title={
                                    crucialPropertyKeys.length > 0
                                        ? `${crucialPropertyKeys.length === 1 ? 'Property' : 'Properties'} ${humanList(
                                              crucialPropertyKeys.map((key) => `\`${key}\``)
                                          )} ${
                                              crucialPropertyKeys.length === 1 ? 'is' : 'are'
                                          } relevant to this insight's results, because ${
                                              crucialPropertyKeys.length === 1 ? "it's" : "they're"
                                          } used in its filters. This timeline higlights how ${
                                              crucialPropertyKeys.length === 1
                                                  ? 'that crucial property has'
                                                  : 'those crucial properties have'
                                          } been changing within this data point's time range.`
                                        : "This insight doesn't rely on any actor properties in its filters, so this timeline only shows properties for the first relevant event."
                                }
                            >
                                <IconInfo className="ml-1 text-muted text-xl shrink-0" />
                            </Tooltip>
                        )}
                    </>
                }
                selectedPointIndex={selectedPointIndex}
                onPointSelection={setSelectedPointIndex}
                from={filter.date_from ? dayjsUtcToTimezone(filter.date_from, timezone) : undefined}
                to={filter.date_to ? dayjsUtcToTimezone(filter.date_to, timezone) : undefined}
                loading={resultLoading}
            />
            <LemonDivider className="h-0" />
            <PropertiesTable
                properties={propertiesShown}
                nestingLevel={1}
                highlightedKeys={crucialPropertyKeys}
                sortProperties
            />
        </div>
    )
}
