import { PostHog } from 'posthog-js'

import { IconCheck, IconEye, IconHide, IconStethoscope, IconWarning, IconX } from '@posthog/icons'
import { LemonBadge, Spinner } from '@posthog/lemon-ui'

import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'

import { PII_MASKING_PRESET_COLORS } from '~/toolbar/bar/piiMaskingStyles'

function EnabledStatusItem({ label, value }: { label: string; value: boolean }): JSX.Element {
    return (
        <div className="flex justify-between items-center w-full">
            <div>{label}: </div>
            <div>{value ? <IconCheck /> : <IconX />}</div>
        </div>
    )
}

export function postHogDebugInfoMenuItem(
    posthog: PostHog | null,
    loadingSurveys: boolean,
    surveysCount: number
): LemonMenuItem {
    const isAutocaptureEnabled = posthog?.autocapture?.isEnabled

    return {
        icon: <IconStethoscope />,
        label: 'Debug info',
        items: [
            {
                label: (
                    <div className="flex justify-between items-center w-full">
                        <div>version: </div>
                        <div>{posthog?.version || 'posthog not available'}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex justify-between items-center w-full">
                        <div>api host: </div>
                        <div>{posthog?.config.api_host}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex justify-between items-center w-full">
                        <div>ui host: </div>
                        <div>{posthog?.config.ui_host || 'not set'}</div>
                    </div>
                ),
            },
            { label: <EnabledStatusItem label="autocapture" value={!!isAutocaptureEnabled} /> },
            {
                label: (
                    <EnabledStatusItem
                        label="rageclicks"
                        value={!!(isAutocaptureEnabled && posthog?.config.rageclick)}
                    />
                ),
            },
            {
                label: (
                    <EnabledStatusItem
                        label="dead clicks"
                        value={!!posthog?.deadClicksAutocapture?.lazyLoadedDeadClicksAutocapture}
                    />
                ),
            },
            { label: <EnabledStatusItem label="heatmaps" value={!!posthog?.heatmaps?.isEnabled} /> },
            {
                label: (
                    <div className="flex justify-between items-center w-full">
                        <div>surveys: </div>
                        <div>
                            {loadingSurveys ? <Spinner /> : <LemonBadge.Number showZero={true} count={surveysCount} />}
                        </div>
                    </div>
                ),
            },
            { label: <EnabledStatusItem label="session recording" value={!!posthog?.sessionRecording?.started} /> },
            {
                label: (
                    <div className="flex justify-between items-center w-full">
                        <div>session recording status: </div>
                        <div>{posthog?.sessionRecording?.status || 'unknown'}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex items-center w-full">
                        <Link to={posthog?.get_session_replay_url()} target="_blank">
                            View current session recording
                        </Link>
                    </div>
                ),
            },
        ],
    }
}

export function piiMaskingMenuItem(
    piiMaskingEnabled: boolean,
    piiMaskingColor: string,
    togglePiiMasking: () => void,
    setPiiMaskingColor: (color: string) => void,
    piiWarning: string[] | null
): LemonMenuItem[] {
    return [
        {
            icon: piiMaskingEnabled ? <IconEye /> : <IconHide />,
            label: piiMaskingEnabled ? 'Show PII' : 'Hide PII',
            sideIcon: piiWarning && piiWarning.length > 0 ? <IconWarning className="text-warning" /> : undefined,
            tooltip: piiWarning && piiWarning.length > 0 ? piiWarning.join('\n') : undefined,
            onClick: (e: React.MouseEvent) => {
                e.preventDefault()
                e.stopPropagation()
                togglePiiMasking()
            },
            custom: true,
        },
        piiMaskingEnabled
            ? {
                  icon: (
                      <div
                          className="w-4 h-4 rounded border"
                          // eslint-disable-next-line react/forbid-dom-props
                          style={{ backgroundColor: piiMaskingColor }}
                      />
                  ),
                  label: 'PII masking color',
                  placement: 'right',
                  disabled: !piiMaskingEnabled,
                  items: PII_MASKING_PRESET_COLORS.map((preset) => ({
                      icon: (
                          <div
                              className="w-4 h-4 rounded border"
                              // eslint-disable-next-line react/forbid-dom-props
                              style={{ backgroundColor: preset.value }}
                          />
                      ),
                      label: preset.label,
                      onClick: () => {
                          setPiiMaskingColor(preset.value)
                      },
                      active: piiMaskingColor === preset.value,
                      custom: true,
                  })),
              }
            : undefined,
    ].filter(Boolean) as LemonMenuItem[]
}
