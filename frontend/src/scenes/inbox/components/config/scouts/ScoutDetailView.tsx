import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { inboxSceneLogic } from '../../../inboxSceneLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SCOUT_RUNS_WINDOW_SPAN, scoutRunsWindowLabel } from '../../../utils/scoutRunsWindow'
import { ScoutRowCard } from './ScoutRowCard'

/**
 * Full-width scout detail surface, rendered over the inbox list at `/inbox/scouts/:skillName`.
 * Skeleton (W1): back link, the shared `ScoutRowCard` as the header, and the recent-window
 * rollup line. The Signals section (emission cards) and per-scout run history land next (W2/W3).
 */
export function ScoutDetailView({ skillName }: { skillName: string }): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, rollups, runsWindowComplete } = useValues(scoutFleetLogic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)
    const { setSelectedScoutSkillName } = useActions(inboxSceneLogic)

    const config = scoutConfigs?.find((c) => c.skill_name === skillName) ?? null
    const rollup = rollups.get(skillName)

    return (
        <div className="flex flex-col min-h-0 flex-1 overflow-auto gap-4 px-4 py-3">
            <LemonButton
                type="tertiary"
                size="small"
                icon={<IconArrowLeft />}
                onClick={() => setSelectedScoutSkillName(null)}
                className="self-start"
            >
                Scouts
            </LemonButton>

            {config === null ? (
                scoutConfigsLoading ? (
                    <LemonSkeleton className="h-16 w-full rounded" />
                ) : (
                    <div className="flex flex-1 items-center justify-center text-sm text-tertiary">
                        Scout not found.
                    </div>
                )
            ) : (
                <>
                    <ScoutRowCard config={config} rollup={rollup} onUpdate={updateScoutConfig} asHeader />

                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-default uppercase tracking-wide">
                            Last {SCOUT_RUNS_WINDOW_SPAN}
                        </span>
                        <span className="text-sm text-secondary">
                            {rollup && rollup.runCount > 0 ? (
                                <>
                                    {pluralize(rollup.runCount, 'run')} · {rollup.completedCount} completed ·{' '}
                                    {rollup.failedCount} failed · {pluralize(rollup.emittedCount, 'signal')} emitted
                                </>
                            ) : (
                                'No runs in this window.'
                            )}
                            <span className="text-muted"> · {scoutRunsWindowLabel(runsWindowComplete)}</span>
                        </span>
                    </div>

                    <div className="rounded border border-dashed border-primary bg-bg-light px-4 py-6 text-center text-sm text-muted">
                        Signals and run history are coming to this view soon.
                    </div>
                </>
            )}
        </div>
    )
}
