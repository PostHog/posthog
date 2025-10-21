import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconBrowser } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { FilterPanel } from 'scenes/heatmaps/components/FilterPanel'
import { HeatmapHeader } from 'scenes/heatmaps/components/HeatmapHeader'
import { urls } from 'scenes/urls'

import { ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { heatmapLogic } from './heatmapLogic'

export function HeatmapScene({ id }: { id: string }): JSX.Element {
    const logicProps = { id: id }
    const logic = heatmapLogic(logicProps)

    const { name, loading, type, displayUrl, widthOverride, screenshotUrl, screenshotLoading, generatingScreenshot } =
        useValues(logic)
    const { setName, updateHeatmap, onIframeLoad } = useActions(logic)

    const [actualImageDimensions, setActualImageDimensions] = useState<{ width: number; height: number } | null>(null)
    const imageRef = useRef<HTMLImageElement>(null)

    const handleImageLoad = useCallback(() => {
        if (imageRef.current) {
            const { offsetWidth, offsetHeight } = imageRef.current
            setActualImageDimensions({ width: offsetWidth, height: offsetHeight })
        }
    }, [])

    const debouncedOnNameChange = useDebouncedCallback((name: string) => {
        setName(name)
    }, 500)

    if (loading) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    return (
        <BindLogic logic={heatmapLogic} props={logicProps}>
            <SceneContent>
                <SceneTitleSection
                    name={name || 'No name'}
                    resourceType={{
                        type: 'heatmap',
                    }}
                    description={null}
                    canEdit
                    onNameChange={debouncedOnNameChange}
                    forceBackTo={{
                        name: 'Heatmaps',
                        path: urls.heatmaps(),
                        key: 'heatmaps',
                    }}
                    actions={
                        <LemonButton type="primary" onClick={updateHeatmap} size="small">
                            Save
                        </LemonButton>
                    }
                />
                <ScenePanelDivider />
                <HeatmapHeader />
                <FilterPanel />
                <ScenePanelDivider />
                <div className="border bg-white rounded-lg">
                    <div className="p-2 border-b text-muted-foreground gap-x-2 flex items-center">
                        <IconBrowser /> {displayUrl}
                    </div>
                    {type === 'screenshot' ? (
                        <div
                            className="relative flex w-full justify-center flex-1"
                            style={{ width: actualImageDimensions?.width ?? widthOverride ?? '100%' }}
                        >
                            {(screenshotLoading || generatingScreenshot) && (
                                <div className="absolute inset-0 flex items-center justify-center">
                                    <Spinner />
                                </div>
                            )}
                            {screenshotUrl && (
                                <>
                                    <HeatmapCanvas
                                        positioning="absolute"
                                        widthOverride={actualImageDimensions?.width ?? widthOverride}
                                        context="in-app"
                                    />
                                    <img
                                        id="heatmap-screenshot"
                                        ref={imageRef}
                                        src={screenshotUrl}
                                        style={{
                                            maxWidth: widthOverride ?? '100%',
                                            height: 'auto',
                                            display: 'block',
                                        }}
                                        onLoad={handleImageLoad}
                                        className="rounded-b-lg"
                                        onError={() => {
                                            console.error('Failed to load screenshot')
                                        }}
                                    />
                                </>
                            )}
                        </div>
                    ) : (
                        <div className="relative min-h-screen">
                            <HeatmapCanvas positioning="absolute" widthOverride={widthOverride} context="in-app" />
                            <iframe
                                id="heatmap-iframe"
                                className="min-h-screen bg-white rounded-b-lg"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ width: widthOverride ?? '100%' }}
                                src={displayUrl || ''}
                                onLoad={onIframeLoad}
                                // these two sandbox values are necessary so that the site and toolbar can run
                                // this is a very loose sandbox,
                                // but we specify it so that at least other capabilities are denied
                                sandbox="allow-scripts allow-same-origin"
                                // we don't allow things such as camera access though
                                allow=""
                            />
                        </div>
                    )}
                </div>
            </SceneContent>
        </BindLogic>
    )
}
