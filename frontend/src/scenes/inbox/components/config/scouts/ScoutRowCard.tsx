import clsx from 'clsx'
import { useActions } from 'kea'
import { useState } from 'react'

import { IconArrowUpRight, IconGear } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SignalScoutConfig, SignalScoutConfigUpdate } from '../../../types'
import { formatRunIntervalShort, prettifyScoutSkillName, ScoutRollup } from '../../../utils/scoutRunsWindow'
import { agentSetupModalLogic } from '../../shell/agentSetupModalLogic'
import { ScoutOriginBadge } from './ScoutBadges'
import { ScoutConfigForm, ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutRunBoxes } from './ScoutRunBoxes'

/**
 * The one scout card: name, badges, cadence, emitted count, run boxes, enable
 * switch, and a gear that expands the settings form.
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
    // Prefer the skill's explicit display name (e.g. "Owner - <plan title>" on plan owner scouts)
    // over a prettified version of the deterministic skill name.
    const displayName = config.display_name || prettifyScoutSkillName(config.skill_name)

    return (
        <div
            className={clsx(
                'flex flex-col rounded border border-primary bg-bg-light px-4 py-3',
                !asHeader && 'group transition-colors hover:border-primary-3000 hover:bg-bg-3000',
                !config.enabled && 'opacity-65'
            )}
        >
            <div className="flex items-center gap-4">
                {/* Name + badges on top, cadence/emitted as a muted subtitle below — keeps the
                    metadata off the main row so the sparkline and controls have room to breathe. */}
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                        {asHeader ? (
                            // min-w keeps the name from being squeezed to zero width by the
                            // trailing badges — truncate should clip to an ellipsis, never vanish.
                            <span className="truncate font-medium text-sm min-w-[6rem]">{displayName}</span>
                        ) : (
                            <Tooltip
                                title={
                                    <div className="flex flex-col gap-1 max-w-sm">
                                        {config.description ? (
                                            <span className="line-clamp-6">{config.description}</span>
                                        ) : null}
                                        <span className="text-muted">{config.skill_name} · view scout</span>
                                    </div>
                                }
                            >
                                <Link
                                    to={urls.inboxScout(config.skill_name)}
                                    // The fleet list lives in the setup modal, which portals outside the
                                    // (hidden) list subtree — close it so it doesn't cover the detail page.
                                    onClick={() => closeSetupModal()}
                                    subtle
                                    className="truncate font-medium text-sm min-w-[6rem]"
                                >
                                    {displayName}
                                </Link>
                            </Tooltip>
                        )}
                        {/* Badges hug the name instead of being shoved to the column's right edge.
                            They never shrink (shrink-0); the name absorbs width pressure by shrinking
                            and truncating (down to its min-w floor), so the pill is never sliced. */}
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
                        </div>
                    </div>
                    <div className="flex items-center gap-1 whitespace-nowrap text-[11px] text-muted">
                        <span>{formatRunIntervalShort(config.run_interval_minutes)}</span>
                        {rollup && rollup.emittedCount > 0 ? (
                            <span>· {pluralize(rollup.emittedCount, 'signal')} emitted</span>
                        ) : null}
                    </div>
                </div>
                {/* The sparkline is the flexible region: it shrinks and clips the oldest runs
                    off the left so it can never push the controls column off the row. */}
                <div className="flex min-w-0 overflow-hidden">
                    <ScoutRunBoxes runs={rollup?.runs ?? []} />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <ScoutEnabledSwitch config={config} onUpdate={onUpdate} />
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
