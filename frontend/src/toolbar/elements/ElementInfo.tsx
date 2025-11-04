import { useActions, useValues } from 'kea'

import { IconCalendar, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ActionStep } from '~/toolbar/actions/ActionStep'
import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapToolbarMenuLogic } from '~/toolbar/elements/heatmapToolbarMenuLogic'

import { actionsTabLogic } from '../actions/actionsTabLogic'
import { ElementStatistic } from './ElementStatistic'
import { SelectorQualityWarning } from './SelectorQualityWarning'

export function ElementInfo(): JSX.Element | null {
    const { clickCount: totalClickCount, dateRange } = useValues(heatmapToolbarMenuLogic)

    const { activeMeta } = useValues(elementsLogic)
    const { createAction } = useActions(elementsLogic)
    const { automaticActionCreationEnabled } = useValues(actionsTabLogic)

    if (!activeMeta) {
        return null
    }

    const { element, position, count, clickCount, rageclickCount, deadclickCount, actionStep } = activeMeta

    return (
        <>
            <div className="p-3 border-l-[5px] border-l-warning bg-bg-light">
                <h1 className="section-title">Selected Element</h1>
                <ActionStep actionStep={actionStep} />

                <div className="mt-2">
                    <SelectorQualityWarning
                        selector={actionStep?.selector}
                        element={element}
                        compact={true}
                        minSeverity="fragile"
                    />
                </div>
            </div>

            {position ? (
                <div className="p-3 border-l-[5px] border-l-danger bg-surface-primary text-primary">
                    <h1 className="section-title">Stats</h1>
                    <p className="">
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
                        <ElementStatistic title="Deadclicks" value={deadclickCount || 0} />
                    </div>
                </div>
            ) : null}

            <div className="p-3 border-l-[5px] border-l-success bg-surface-secondary">
                {!automaticActionCreationEnabled && (
                    <>
                        <h1 className="section-title">Actions ({activeMeta.actions.length})</h1>

                        {activeMeta.actions.length === 0 ? (
                            <p className="text-primary">No actions include this element</p>
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
