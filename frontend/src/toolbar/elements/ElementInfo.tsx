import { IconCalendar, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { ActionStep } from '~/toolbar/actions/ActionStep'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { actionsTabLogic } from '../actions/actionsTabLogic'

function ElementStatistic({
    prefix,
    suffix,
    title,
    value,
}: {
    title: string
    value: string | number
    prefix?: string
    suffix?: string
}): JSX.Element {
    return (
        <div className="flex flex-col">
            <div>{title}</div>
            <div className="text-2xl">
                {prefix}
                {value} {suffix}
            </div>
        </div>
    )
}

export function ElementInfo(): JSX.Element | null {
    const { clickCount: totalClickCount, dateRange } = useValues(heatmapLogic)

    const { activeMeta } = useValues(elementsLogic)
    const { createAction } = useActions(elementsLogic)
    const { automaticActionCreationEnabled } = useValues(actionsTabLogic)

    if (!activeMeta) {
        return null
    }

    const { element, position, count, clickCount, rageclickCount, actionStep } = activeMeta

    return (
        <>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="p-3" style={{ borderLeft: '5px solid #8F98FF', background: 'hsla(235, 100%, 99%, 1)' }}>
                <h1 className="section-title">Selected Element</h1>
                <ActionStep actionStep={actionStep} />
            </div>
            {position ? (
                /* eslint-disable-next-line react/forbid-dom-props */
                <div className="p-3" style={{ borderLeft: '5px solid #FF9870', background: 'hsla(19, 99%, 99%, 1)' }}>
                    <h1 className="section-title">Stats</h1>
                    <p>
                        <IconCalendar /> <u>{dateRange}</u>
                    </p>
                    <div className="flex flex-row gap-4">
                        <div className="w-2/3">
                            <ElementStatistic
                                title="Clicks"
                                value={count || 0}
                                suffix={`/ ${totalClickCount} (${
                                    totalClickCount === 0
                                        ? '-'
                                        : Math.round(((count || 0) / totalClickCount) * 10000) / 100
                                }%)`}
                            />
                        </div>
                        <div className="w-1/3">
                            <ElementStatistic title="Ranking" prefix="#" value={position || 0} />
                        </div>
                    </div>
                    <div className="flex flex-row gap-4 mt-2">
                        <ElementStatistic title="Autocapture clicks" value={clickCount || 0} />
                        <ElementStatistic title="Rageclicks" value={rageclickCount || 0} />
                    </div>
                </div>
            ) : null}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="p-3" style={{ borderLeft: '5px solid #94D674', background: 'hsla(100, 74%, 98%, 1)' }}>
                {!automaticActionCreationEnabled && (
                    <>
                        <h1 className="section-title">Actions ({activeMeta.actions.length})</h1>

                        {activeMeta.actions.length === 0 ? (
                            <p>No actions include this element</p>
                        ) : (
                            <ActionsListView actions={activeMeta.actions.map((a) => a.action)} />
                        )}
                    </>
                )}

                <LemonButton size="small" type="secondary" onClick={() => createAction(element)} icon={<IconPlus />}>
                    {automaticActionCreationEnabled ? 'Select element' : 'Create a new action'}
                </LemonButton>
            </div>
        </>
    )
}
