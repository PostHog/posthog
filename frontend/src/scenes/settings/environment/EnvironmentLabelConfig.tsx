import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { EnvironmentLabel } from 'lib/components/EnvironmentLabel/EnvironmentLabel'
import {
    DEFAULT_ENVIRONMENT_LABEL_COLOR,
    ENVIRONMENT_LABEL_COLORS,
    ENVIRONMENT_LABEL_TEMPLATES,
    EnvironmentLabelTemplate,
} from 'lib/components/EnvironmentLabel/environmentLabels'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { EnvironmentLabelColor } from '~/types'

const MAX_LABEL_LENGTH = 30

export function EnvironmentLabelConfig(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [label, setLabel] = useState<string>(currentTeam?.environment_label ?? '')
    const [color, setColor] = useState<EnvironmentLabelColor>(
        currentTeam?.environment_color ?? DEFAULT_ENVIRONMENT_LABEL_COLOR
    )

    // Re-sync when the team changes underneath us (e.g. switched project, server refresh).
    useEffect(() => {
        setLabel(currentTeam?.environment_label ?? '')
        setColor(currentTeam?.environment_color ?? DEFAULT_ENVIRONMENT_LABEL_COLOR)
    }, [currentTeam?.id, currentTeam?.environment_label, currentTeam?.environment_color])

    const savedLabel = currentTeam?.environment_label ?? ''
    const savedColor = currentTeam?.environment_color ?? DEFAULT_ENVIRONMENT_LABEL_COLOR
    const trimmedLabel = label.trim()
    const isDirty = trimmedLabel !== savedLabel.trim() || (trimmedLabel !== '' && color !== savedColor)
    const canClear = savedLabel.trim() !== ''

    const activeTemplate = useMemo<EnvironmentLabelTemplate | undefined>(
        () =>
            ENVIRONMENT_LABEL_TEMPLATES.find(
                (template) => template.label.toLowerCase() === trimmedLabel.toLowerCase() && template.color === color
            ),
        [trimmedLabel, color]
    )

    const handleTemplateClick = (template: EnvironmentLabelTemplate): void => {
        setLabel(template.label)
        setColor(template.color)
    }

    const handleSave = (): void => {
        updateCurrentTeam({
            environment_label: trimmedLabel || null,
            environment_color: trimmedLabel ? color : null,
        })
    }

    const handleClear = (): void => {
        setLabel('')
        setColor(DEFAULT_ENVIRONMENT_LABEL_COLOR)
        updateCurrentTeam({ environment_label: null, environment_color: null })
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <p className="text-secondary mb-0">
                Tag this environment with a label like <strong>Production</strong> or <strong>Staging</strong>. The
                label appears in the project switcher and next to the project name in the navigation so it's hard to
                miss which environment you're in.
            </p>

            {/* Templates */}
            <div>
                <div className="text-xs font-semibold text-secondary mb-2 uppercase tracking-wide">Quick presets</div>
                <div className="flex flex-wrap gap-2">
                    {ENVIRONMENT_LABEL_TEMPLATES.map((template) => {
                        const isActive = activeTemplate?.label === template.label
                        return (
                            <button
                                key={template.label}
                                type="button"
                                onClick={() => handleTemplateClick(template)}
                                disabled={!!restrictedReason}
                                title={template.description}
                                className={cn(
                                    'flex items-center gap-2 px-2 py-1 rounded border text-sm transition-colors',
                                    'hover:bg-fill-highlight-50 disabled:cursor-not-allowed disabled:opacity-60',
                                    isActive ? 'border-accent bg-fill-highlight-50' : 'border-primary'
                                )}
                            >
                                <EnvironmentLabel label={template.label} color={template.color} size="xs" />
                                {isActive && <IconCheck className="text-accent" />}
                            </button>
                        )
                    })}
                </div>
            </div>

            {/* Label input */}
            <div>
                <div className="text-xs font-semibold text-secondary mb-2 uppercase tracking-wide">Label</div>
                <LemonInput
                    value={label}
                    onChange={(value) => setLabel(value.slice(0, MAX_LABEL_LENGTH))}
                    placeholder="e.g. Production"
                    disabledReason={restrictedReason}
                    maxLength={MAX_LABEL_LENGTH}
                />
            </div>

            {/* Color picker */}
            <div>
                <div className="text-xs font-semibold text-secondary mb-2 uppercase tracking-wide">Color</div>
                <div className="flex flex-wrap gap-2">
                    {ENVIRONMENT_LABEL_COLORS.map((option) => {
                        const isActive = color === option.key
                        return (
                            <button
                                key={option.key}
                                type="button"
                                aria-label={option.name}
                                aria-pressed={isActive}
                                onClick={() => setColor(option.key)}
                                disabled={!!restrictedReason}
                                title={option.name}
                                className={cn(
                                    'relative size-7 rounded-full border-2 transition-all',
                                    'disabled:cursor-not-allowed disabled:opacity-60',
                                    isActive
                                        ? 'border-accent scale-110 shadow-sm'
                                        : 'border-transparent hover:border-secondary'
                                )}
                            >
                                <span className={cn('absolute inset-1 rounded-full', option.dotClassName)} />
                            </button>
                        )
                    })}
                </div>
            </div>

            {/* Preview */}
            <div className="bg-surface-secondary rounded p-3 flex items-center gap-2">
                <span className="text-secondary text-xs uppercase tracking-wide font-semibold">Preview:</span>
                {trimmedLabel ? (
                    <div className="flex items-center gap-2 min-w-0">
                        <span className="font-semibold truncate">{currentTeam?.name ?? 'This environment'}</span>
                        <EnvironmentLabel label={trimmedLabel} color={color} />
                    </div>
                ) : (
                    <span className="italic text-tertiary text-sm">No label — set one above to preview</span>
                )}
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabled={!isDirty || !!restrictedReason}
                    disabledReason={restrictedReason}
                    loading={currentTeamLoading}
                >
                    Save label
                </LemonButton>
                {canClear && (
                    <LemonButton
                        type="secondary"
                        onClick={handleClear}
                        disabled={!!restrictedReason}
                        disabledReason={restrictedReason}
                    >
                        Remove label
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
