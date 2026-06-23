import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowUpRight, IconGear, IconSparkles } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SignalScoutConfig, SignalScoutConfigUpdate } from '../../../types'
import {
    buildScoutCheckinPrompt,
    formatRunIntervalShort,
    prettifyScoutSkillName,
    ScoutRollup,
} from '../../../utils/scoutRunsWindow'
import { agentSetupModalLogic } from '../../shell/agentSetupModalLogic'
import { DryRunBadge, ScoutOriginBadge } from './ScoutBadges'
import { ScoutConfigForm, ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutRunBoxes } from './ScoutRunBoxes'

/**
 * The one scout card: name, badges, cadence, emitted count, run boxes, enable
 * switch, a chat check-in button, and a gear that expands the settings form.
 */
export function ScoutRowCard({
    config,
    rollup,
    onUpdate,
    asHeader = false,
}: {
    config: SignalScoutConfig
    rollup: ScoutRollup | undefined
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    /** When rendered as the scout detail header the name is plain text (the row IS the page). */
    asHeader?: boolean
}): JSX.Element {
    const [settingsOpen, setSettingsOpen] = useState(false)
    const { closeSetupModal } = useActions(agentSetupModalLogic)
    const displayName = prettifyScoutSkillName(config.skill_name)

    return (
        <div
            className={clsx(
                'flex flex-col rounded border border-primary bg-bg-light px-4 py-3',
                !asHeader && 'group transition-colors hover:border-primary-3000 hover:bg-bg-3000',
                !config.enabled && 'opacity-65'
            )}
        >
            <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                    {asHeader ? (
                        // min-w keeps the name from being squeezed to zero width by the
                        // trailing metadata (badges, cadence, emitted count) — truncate
                        // should clip to an ellipsis, never vanish entirely.
                        <span className="truncate font-medium text-sm min-w-[6rem] flex-1">{displayName}</span>
                    ) : (
                        <Tooltip title={`${config.skill_name} · view scout`}>
                            <Link
                                to={urls.inboxScout(config.skill_name)}
                                // The fleet list lives in the setup modal, which portals outside the
                                // (hidden) list subtree — close it so it doesn't cover the detail page.
                                onClick={() => closeSetupModal()}
                                subtle
                                className="truncate font-medium text-sm min-w-[6rem] flex-1"
                            >
                                {displayName}
                            </Link>
                        </Tooltip>
                    )}
                    {/* Icon + badges never shrink: the name (flex-1) absorbs width pressure and
                        truncates, so the Custom/Canonical pill is never sliced mid-badge. */}
                    <div className="flex items-center gap-2 shrink-0">
                        <Tooltip title={`${config.skill_name} · open skill`}>
                            <Link
                                to={urls.skill(config.skill_name)}
                                target="_blank"
                                targetBlankIcon={false}
                                subtle
                                className="text-muted"
                                aria-label={`Open the ${config.skill_name} skill`}
                            >
                                <IconArrowUpRight className="size-3.5" />
                            </Link>
                        </Tooltip>
                        <ScoutOriginBadge skillName={config.skill_name} />
                        <DryRunBadge config={config} />
                    </div>
                </div>
                {/* Cadence + emitted count get their own non-shrinking column so they can't
                    overlap the sparkline (the name group absorbs any width pressure). */}
                <div className="flex items-center gap-1 shrink-0 whitespace-nowrap text-[11px] text-muted">
                    <span>{formatRunIntervalShort(config.run_interval_minutes)}</span>
                    {rollup && rollup.emittedCount > 0 ? (
                        <span>· {pluralize(rollup.emittedCount, 'signal')} emitted</span>
                    ) : null}
                </div>
                {/* The sparkline is the flexible region: it shrinks and clips the oldest runs
                    off the left so it can never push the controls column off the row. */}
                <div className="flex min-w-0 overflow-hidden">
                    <ScoutRunBoxes runs={rollup?.runs ?? []} />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <ScoutEnabledSwitch config={config} onUpdate={onUpdate} />
                    <ScoutChatButton skillName={config.skill_name} />
                    <Tooltip title="Scout settings">
                        <LemonButton
                            size="small"
                            icon={<IconGear />}
                            active={settingsOpen}
                            onClick={() => setSettingsOpen((value) => !value)}
                            aria-label={`${config.skill_name} settings`}
                        />
                    </Tooltip>
                </div>
            </div>
            {settingsOpen ? (
                <div className="mt-3 border-t border-primary pt-3">
                    <ScoutConfigForm config={config} onUpdate={onUpdate} />
                </div>
            ) : null}
        </div>
    )
}

/**
 * Icon-only chat CTA on the row: fires a one-click auto-mode cloud task asking
 * about this specific scout, then navigates to it.
 */
function ScoutChatButton({ skillName }: { skillName: string }): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { chatTaskRunning } = useValues(scoutFleetLogic)
    return (
        <Tooltip title="Ask PostHog about this scout">
            <LemonButton
                size="small"
                icon={<IconSparkles />}
                loading={chatTaskRunning}
                disabledReason={chatTaskRunning ? 'Starting a task…' : undefined}
                onClick={() =>
                    startScoutChatTask(
                        buildScoutCheckinPrompt(skillName, prettifyScoutSkillName(skillName)),
                        'scout check-in',
                        `Scout check-in: ${prettifyScoutSkillName(skillName)}`
                    )
                }
                aria-label={`Ask PostHog about the ${skillName} scout`}
            />
        </Tooltip>
    )
}
