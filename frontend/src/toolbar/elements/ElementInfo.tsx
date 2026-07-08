import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ElementClickStats } from 'lib/components/heatmaps/ElementClickStats'

import { ActionsListView } from '~/toolbar/actions/ActionsListView'
import { ActionStep } from '~/toolbar/actions/ActionStep'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapToolbarMenuLogic } from '~/toolbar/elements/heatmapToolbarMenuLogic'

import { actionsTabLogic } from '../actions/actionsTabLogic'
import { SelectorQualityWarning } from './SelectorQualityWarning'

export function ElementInfo(): JSX.Element | null {
    const { clickCount: totalClickCount, dateRange } = useValues(heatmapToolbarMenuLogic)

    const { activeMeta } = useValues(elementsLogic)
    const { createAction } = useActions(elementsLogic)
    const { automaticActionCreationEnabled } = useValues(actionsTabLogic)

    if (!activeMeta) {
        return null
    }

    const { element, position, count, clickCount, rageclickCount, deadclickCount, actionStep, actions } = activeMeta

    return (
        <>
            <div className="p-3 border-l-[5px] border-l-warning bg-bg-light">
                <h1 className="section-title">Selected Element</h1>
                {actionStep && <ActionStep actionStep={actionStep} />}

                <SelectorQualityWarning selector={actionStep?.selector} compact />
            </div>

            {position ? (
                <div className="p-3 border-l-[5px] border-l-danger bg-surface-primary text-primary">
                    <h1 className="section-title">Stats</h1>
                    <ElementClickStats
                        count={count || 0}
                        totalCount={totalClickCount}
                        rank={position || 0}
                        clickCount={clickCount || 0}
                        rageclickCount={rageclickCount || 0}
                        deadclickCount={deadclickCount || 0}
                        dateRange={dateRange ?? undefined}
                    />
                </div>
            ) : null}

            <div className="p-3 border-l-[5px] border-l-success bg-surface-secondary">
                {!automaticActionCreationEnabled && (
                    <>
                        <h1 className="section-title">Actions ({actions?.length ?? 0})</h1>

                        {!actions || actions.length === 0 ? (
                            <p className="text-primary">No actions include this element</p>
                        ) : (
                            <ActionsListView actions={actions.map((a) => a.action)} />
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
