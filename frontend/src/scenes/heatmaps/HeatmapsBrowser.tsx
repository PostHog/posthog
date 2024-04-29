import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useRef } from 'react'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

export function HeatmapsBrowser(): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)
    const logic = heatmapsBrowserLogic({ iframeRef })

    const { browserSearchOptions, browserUrl } = useValues(logic)
    const { setBrowserSearch, setBrowserUrl, onIframeLoad } = useActions(logic)

    return (
        <div className="flex flex-wrap gap-2">
            {/* <div className="border rounded bg-bg-light flex-1">
                <p className="p-2">Controls</p>
            </div> */}

            <div className="flex flex-col overflow-hidden w-full h-[90vh] rounded border">
                <div className="bg-accent-3000 p-2 border-b flex items-center gap-2">
                    <span className="flex-1">
                        <LemonInputSelect
                            mode="single"
                            allowCustomValues
                            placeholder="e.g. https://your-website.com/pricing"
                            onInputChange={(e) => setBrowserSearch(e)}
                            value={browserUrl ? [browserUrl] : undefined}
                            onChange={(v) => setBrowserUrl(v[0] ?? null)}
                            options={
                                browserSearchOptions?.map((x) => ({
                                    label: x,
                                    key: x,
                                })) ?? []
                            }
                        />
                    </span>

                    <LemonButton
                        type="secondary"
                        sideIcon={<IconOpenInNew />}
                        to={
                            browserUrl
                                ? appEditorUrl(browserUrl, {
                                      userIntent: 'heatmaps',
                                  })
                                : undefined
                        }
                        targetBlank
                        disabledReason={!browserUrl ? 'Select a URL first' : undefined}
                    >
                        Open in toolbar
                    </LemonButton>
                </div>

                {browserUrl ? (
                    <iframe
                        ref={iframeRef}
                        className="w-full h-full"
                        src={appEditorUrl(browserUrl, {
                            userIntent: 'heatmaps',
                        })}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            background: '#FFF',
                        }}
                        onLoad={onIframeLoad}
                    />
                ) : (
                    <div className="w-full h-full bg-bg-light">
                        <p className="italic m-2">Select a URL</p>
                        {/* TODO: Add a bunch of suggested pages */}
                    </div>
                )}
            </div>
        </div>
    )
}
