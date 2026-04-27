import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { HeatmapsInvalidURL } from 'scenes/heatmaps/components/HeatmapsInvalidURL'
import { heatmapLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapLogic'

export function HeatmapHeader(): JSX.Element {
    const { dataUrl, displayUrl, pageUrlDraft, isPageUrlDraftValid, pageUrlDraftIsPattern, loading, screenshotError } =
        useValues(heatmapLogic)
    const { setDataUrl, setPageUrlDraft, setDataUrlUserTouched, applyPageUrlDraft, regenerateScreenshot } =
        useActions(heatmapLogic)

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
                    <div>
                        <LemonLabel>Heatmap data URL</LemonLabel>
                        <LemonInput
                            size="small"
                            placeholder={displayUrl ? `Same as page URL: ${displayUrl}` : 'Enter a URL'}
                            value={dataUrl ?? ''}
                            onChange={(value) => {
                                setDataUrlUserTouched(true)
                                setDataUrl(value || null)
                            }}
                            fullWidth={true}
                        />
                        <div className="text-xs text-muted mt-1">
                            Add * for wildcards to aggregate data from multiple pages
                        </div>
                        {screenshotError && (
                            <div className="mt-2">
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
                    </div>
                </div>
            </div>
        </>
    )
}
