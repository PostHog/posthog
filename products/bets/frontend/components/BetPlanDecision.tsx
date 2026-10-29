import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import type { BetsDetailApi, BetsWorkApi } from '../generated/api.schemas'
import { betLogic } from '../logics/betLogic'

export function BetPlanDecision({ item, bet }: { item: BetsWorkApi; bet: BetsDetailApi }): JSX.Element | null {
    const { busy, busyOperation, stoppingWork } = useValues(betLogic({ id: bet.id }))
    const { extendWork, openStop, stopWork } = useActions(betLogic({ id: bet.id }))
    const proposedDays = item.plan.proposed_days
    if (!bet.is_owner || !proposedDays) {
        return null
    }
    const extending = busyOperation === `work:${item.id}:extend`
    const stopping = busyOperation === `work:${item.id}:drop`
    if (stoppingWork === item.id) {
        return (
            <div
                className="flex flex-col gap-2"
                role="group"
                aria-label="Stop the experiment"
                onKeyDown={(event) => {
                    if (event.key === 'Escape' && !stopping) {
                        openStop(null)
                    }
                }}
            >
                <Text size="sm" render={<p className="m-0" />}>
                    Stop this experiment? It ends now, without a result.
                </Text>
                <div className="flex flex-wrap items-center gap-2">
                    <Button
                        size="sm"
                        variant="destructive"
                        autoFocus
                        loading={stopping}
                        disabled={busy && !stopping}
                        onClick={() => stopWork(item.id)}
                        data-attr="bets-plan-stop-confirm"
                    >
                        Stop experiment
                    </Button>
                    <Button
                        size="sm"
                        variant="link-muted"
                        disabled={stopping}
                        onClick={() => openStop(null)}
                        data-attr="bets-plan-stop-cancel"
                    >
                        Keep it running
                    </Button>
                </div>
            </div>
        )
    }
    return (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                size="sm"
                variant="primary"
                loading={extending}
                disabled={busy && !extending}
                onClick={() => extendWork(item.id)}
                data-attr="bets-plan-extend"
            >
                Extend to {proposedDays} days
            </Button>
            <Button
                size="sm"
                variant="link-muted"
                disabled={busy}
                onClick={() => openStop(item.id)}
                data-attr="bets-plan-stop"
            >
                Stop
            </Button>
        </div>
    )
}
