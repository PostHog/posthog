import { useActions, useValues } from 'kea'

import { LemonCollapse, LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { HeatmapsForbiddenURL } from 'scenes/heatmaps/components/HeatmapsForbiddenURL'
import { heatmapLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapLogic'

export interface HeatmapAdvancedSettingsProps {
    dataUrlPlaceholderFallback: string
    dataUrlHelp: React.ReactNode
    consentHelp: React.ReactNode
    showForbiddenUrl?: boolean
    showDataUrl?: boolean
    showConsent?: boolean
    header?: string
}

export function HeatmapAdvancedSettings({
    dataUrlPlaceholderFallback,
    dataUrlHelp,
    consentHelp,
    showForbiddenUrl = false,
    showDataUrl = true,
    showConsent = true,
    header = 'Advanced settings',
}: HeatmapAdvancedSettingsProps): JSX.Element {
    const { dataUrl, displayUrl, type, blockConsentModals, isBrowserUrlAuthorized } = useValues(heatmapLogic)
    const { setDataUrl, setDataUrlUserTouched, setBlockConsentModals } = useActions(heatmapLogic)

    return (
        <LemonCollapse
            panels={[
                {
                    key: 'advanced',
                    header,
                    content: (
                        <div className="flex flex-col gap-4">
                            {showDataUrl ? (
                                <div>
                                    <LemonLabel>Heatmap data URL</LemonLabel>
                                    <LemonInput
                                        size="small"
                                        placeholder={
                                            displayUrl ? `Same as page URL: ${displayUrl}` : dataUrlPlaceholderFallback
                                        }
                                        value={dataUrl ?? ''}
                                        onChange={(value) => {
                                            setDataUrlUserTouched(true)
                                            setDataUrl(value || null)
                                        }}
                                        fullWidth={true}
                                    />
                                    <div className="text-xs text-muted mt-1">{dataUrlHelp}</div>
                                    {showForbiddenUrl && dataUrl && !isBrowserUrlAuthorized ? (
                                        <HeatmapsForbiddenURL />
                                    ) : null}
                                </div>
                            ) : null}
                            {showConsent ? (
                                <div>
                                    <LemonSwitch
                                        checked={blockConsentModals}
                                        onChange={setBlockConsentModals}
                                        label="Dismiss cookie & consent banners"
                                        bordered
                                        disabledReason={
                                            type !== 'screenshot' ? 'Only available for screenshot heatmaps' : undefined
                                        }
                                    />
                                    <div className="text-xs text-muted mt-1">{consentHelp}</div>
                                </div>
                            ) : null}
                        </div>
                    ),
                },
            ]}
        />
    )
}
