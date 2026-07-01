import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { HeatmapAdvancedSettings } from 'scenes/heatmaps/components/HeatmapAdvancedSettings'
import { HeatmapsInvalidURL } from 'scenes/heatmaps/components/HeatmapsInvalidURL'
import { heatmapLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapLogic'

export function HeatmapHeader(): JSX.Element {
    const { pageUrlDraft, isPageUrlDraftValid, pageUrlDraftIsPattern, loading, screenshotError } =
        useValues(heatmapLogic)
    const { setPageUrlDraft, applyPageUrlDraft, regenerateScreenshot } = useActions(heatmapLogic)

    const draftIsEmpty = pageUrlDraft.trim() === ''
    const disabledReason = !isPageUrlDraftValid ? 'Enter a valid URL' : draftIsEmpty ? 'Enter a URL' : null

    return (
        <>
            <div className="flex-none md:flex justify-between items-end gap-2 w-full">
                <div className="flex flex-col gap-3 flex-1 min-w-0">
                    <div>
                        <LemonLabel>Page URL</LemonLabel>
                        <div className="flex gap-2 items-start">
                            <LemonInput
                                size="small"
                                placeholder="https://www.example.com/pricing"
                                value={pageUrlDraft}
                                onChange={setPageUrlDraft}
                                onPressEnter={applyPageUrlDraft}
                                fullWidth={true}
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={applyPageUrlDraft}
                                loading={loading}
                                disabledReason={disabledReason}
                            >
                                Regenerate
                            </LemonButton>
                        </div>
                        <div className="text-xs text-muted mt-1">
                            The page we load in the iframe or capture as a screenshot.
                        </div>
                        {pageUrlDraft && !isPageUrlDraftValid ? (
                            pageUrlDraftIsPattern ? (
                                <div className="mt-2">
                                    <LemonBanner type="error">
                                        The page URL can't contain wildcards. Use a concrete URL here and add wildcards
                                        to the heatmap data URL below.
                                    </LemonBanner>
                                </div>
                            ) : (
                                <HeatmapsInvalidURL />
                            )
                        ) : null}
                    </div>
                    {screenshotError && (
                        <div>
                            <LemonBanner
                                type="error"
                                action={{
                                    children: 'Retry',
                                    onClick: regenerateScreenshot,
                                }}
                            >
                                {screenshotError}
                            </LemonBanner>
                        </div>
                    )}
                    <HeatmapAdvancedSettings
                        dataUrlPlaceholderFallback="Enter a URL"
                        dataUrlHelp="Defaults to the page URL. Add * for wildcards to aggregate data from multiple pages."
                        consentHelp="Ask the browser to close cookie/consent popups before capturing the screenshot. This can slow down or fail the render on some sites, so it's off by default. Save to apply."
                    />
                </div>
            </div>
        </>
    )
}
