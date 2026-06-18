import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear, IconSparkles } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SignalScoutConfig, SignalScoutConfigUpdate } from '../../../types'
import {
    buildScoutCheckinPrompt,
    formatRunIntervalShort,
    prettifyScoutSkillName,
    ScoutRollup,
} from '../../../utils/scoutRunsWindow'
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
}: {
    config: SignalScoutConfig
    rollup: ScoutRollup | undefined
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
}): JSX.Element {
    const [settingsOpen, setSettingsOpen] = useState(false)

    return (
        <div
            className={clsx(
                'group flex flex-col rounded border border-primary bg-bg-light px-4 py-3 transition-colors hover:border-primary-3000 hover:bg-bg-3000',
                !config.enabled && 'opacity-65'
            )}
        >
            <div className="flex items-center gap-4">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                    <Tooltip title={config.skill_name}>
                        <span className="truncate font-medium text-sm text-default">
                            {prettifyScoutSkillName(config.skill_name)}
                        </span>
                    </Tooltip>
                    <ScoutOriginBadge skillName={config.skill_name} />
                    <DryRunBadge config={config} />
                    <span className="whitespace-nowrap text-[11px] text-muted">
                        {formatRunIntervalShort(config.run_interval_minutes)}
                    </span>
                    {rollup && rollup.emittedCount > 0 ? (
                        <span className="whitespace-nowrap text-[11px] text-muted">
                            · {pluralize(rollup.emittedCount, 'signal')} emitted
                        </span>
                    ) : null}
                </div>
                <div className="shrink-0">
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
