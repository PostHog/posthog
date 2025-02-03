import { IconCalendar, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { ActionStep } from '~/toolbar/actions/ActionStep'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'

import { actionsTabLogic } from '../actions/actionsTabLogic'
import { ElementStatistic } from './ElementStatistic'

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
            <div className="p-3 border-l-[5px] border-l-warning bg-bg-light">
                <h1 className="section-title">Selected Element</h1>
                <ActionStep actionStep={actionStep} />
            </div>

            {position ? (
                <div className="p-3 border-l-[5px] border-l-danger bg-bg-3000">
                    <h1 className="section-title">Stats</h1>
                    <p>
                        <IconCalendar /> <u>{dateRange}</u>
                    </p>
                    <div className="grid grid-cols-[auto_1fr] gap-4">
                        <ElementStatistic
                            title="Clicks"
                            value={count || 0}
                            suffix={`/${totalClickCount} (${
                                totalClickCount === 0 ? '?' : Math.round(((count || 0) / totalClickCount) * 10000) / 100
                            }%)`}
                        />
                        <ElementStatistic title="Ranking" prefix="#" value={position || 0} />
                        <ElementStatistic title="Autocapture clicks" value={clickCount || 0} />
                        <ElementStatistic title="Rageclicks" value={rageclickCount || 0} />
                    </div>
                </div>
            ) : null}

            <div className="p-3 border-l-[5px] border-l-success bg-bg-3000">
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
                {automaticActionCreationEnabled ? (
                    <LemonButton
                        size="small"
                        type="primary"
                        status="alt"
                        onClick={() => createAction(element)}
                        icon={<IconPlus />}
                    >
                        Select element
                    </LemonButton>
                ) : (
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => createAction(element)}
                        icon={<IconPlus />}
                    >
                        Create a new action
                    </LemonButton>
                )}
            </div>
        </>
    )
}
