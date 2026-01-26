import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconTrash, IconUpload } from '@posthog/icons'
import { LemonFileInput, Spinner } from '@posthog/lemon-ui'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { cn } from 'lib/utils/css-classes'
import { HeatmapsForbiddenURL } from 'scenes/heatmaps/components/HeatmapsForbiddenURL'
import { HeatmapsUrlsList } from 'scenes/heatmaps/components/HeatmapsInfo'
import { HeatmapsInvalidURL } from 'scenes/heatmaps/components/HeatmapsInvalidURL'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { HeatmapType } from '~/types'

import { heatmapLogic } from './heatmapLogic'

export function HeatmapNewScene(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { loading, displayUrl, isDisplayUrlValid, type, name, dataUrl, isBrowserUrlAuthorized, imageUrl } =
        useValues(logic)
    const { setDisplayUrl, setType, setName, createHeatmap, setDataUrl, setImageUrl, setImageWidth } = useActions(logic)

    const { searchParams } = useValues(router)

    // Pre-fill form from URL params (e.g., when redirected from toolbar screenshot capture)
    useEffect(() => {
        const urlType = searchParams.type as string | undefined
        const urlImageUrl = searchParams.image_url as string | undefined
        const urlUrl = searchParams.url as string | undefined
        const urlDataUrl = searchParams.data_url as string | undefined

        if (urlType === 'upload' || urlType === 'screenshot' || urlType === 'iframe') {
            setType(urlType)
        }
        if (urlImageUrl) {
            setImageUrl(urlImageUrl)
        }
        if (urlUrl) {
            setDisplayUrl(urlUrl)
        }
        if (urlDataUrl) {
            setDataUrl(urlDataUrl)
        }
    }, []) // Only run on mount

    const debouncedOnNameChange = useDebouncedCallback((name: string) => {
        setName(name)
    }, 500)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url) => {
            setImageUrl(url)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const getDisabledReason = (): string | null => {
        if (type === 'upload') {
            if (!imageUrl) {
                return 'Please upload an image'
            }
        } else {
            if (!isDisplayUrlValid || !isBrowserUrlAuthorized) {
                return 'Invalid URL or forbidden URL'
            }
            if (!displayUrl) {
                return 'URL is required'
            }
        }
        if (!dataUrl) {
            return 'Heatmap data URL is required'
        }
        return null
    }

    if (loading) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={name}
                resourceType={{
                    type: 'heatmap',
                }}
                description={null}
                canEdit
                forceEdit
                onNameChange={debouncedOnNameChange}
                forceBackTo={{
                    name: 'Heatmaps',
                    path: urls.heatmaps(),
                    key: 'heatmaps',
                }}
            />
            <SceneSection title="Capture method" description="Choose how to display your page in the heatmap">
                <LemonRadio
                    options={[
                        {
                            label: 'Screenshot',
                            value: 'screenshot',
                            description: 'We will generate a full-page screenshot of your website',
                        },
                        {
                            label: 'Iframe',
                            value: 'iframe',
                            description:
                                'We will load your website in an iframe. Make sure you allow your website to be loaded in an iframe.',
                        },
                        {
                            label: 'Upload',
                            value: 'upload',
                            description:
                                'Upload your own screenshot. Useful for auth-protected pages or pages that cannot be captured automatically.',
                        },
                    ]}
                    value={type}
                    onChange={(value: HeatmapType) => setType(value)}
                />
            </SceneSection>
            <SceneDivider />
            {type === 'upload' && (
                <SceneSection
                    title="Upload image"
                    description="Upload a screenshot of your page. The heatmap will be displayed on top of this image."
                >
                    {imageUrl ? (
                        <div className="flex flex-col gap-2">
                            <div className="relative inline-block">
                                <img
                                    src={imageUrl}
                                    alt="Uploaded screenshot"
                                    className="max-w-md max-h-64 rounded border object-contain"
                                    onLoad={(e) => {
                                        const img = e.target as HTMLImageElement
                                        if (img.naturalWidth) {
                                            setImageWidth(img.naturalWidth)
                                        }
                                    }}
                                />
                                <LemonButton
                                    data-attr="heatmap-new-remove-uploaded-image"
                                    icon={<IconTrash />}
                                    size="small"
                                    type="secondary"
                                    status="danger"
                                    className="absolute top-2 right-2"
                                    onClick={() => {
                                        setImageUrl(null)
                                        setImageWidth(null)
                                        setFilesToUpload([])
                                    }}
                                    tooltip="Remove image"
                                />
                            </div>
                        </div>
                    ) : (
                        <LemonFileInput
                            accept="image/*"
                            multiple={false}
                            onChange={setFilesToUpload}
                            loading={uploading}
                            value={filesToUpload}
                            callToAction={
                                <div
                                    className={cn(
                                        'flex flex-col items-center justify-center flex-1 cohort-csv-dragger text-text-3000 deprecated-space-y-1',
                                        'text-primary mt-0 bg-transparent border border-dashed border-primary hover:border-secondary p-8'
                                    )}
                                >
                                    <IconUpload
                                        style={{
                                            fontSize: '3rem',
                                            color: 'var(--color-text-primary)',
                                        }}
                                    />
                                    <div>{filesToUpload[0]?.name ?? 'Choose an image'}</div>
                                </div>
                            }
                        />
                    )}
                </SceneSection>
            )}
            {type !== 'upload' && (
                <SceneSection title="Page URL" description="URL to your website">
                    <LemonInput
                        value={displayUrl || ''}
                        onChange={setDisplayUrl}
                        placeholder="https://www.example.com"
                    />
                    {!isDisplayUrlValid && <HeatmapsInvalidURL />}
                    {!displayUrl && <HeatmapsUrlsList />}
                </SceneSection>
            )}
            <SceneDivider />
            <SceneSection
                title="Heatmap data URL"
                description="An exact match or a pattern for heatmap data. For example, use a pattern if you have pages with dynamic IDs. E.g. https://www.example.com/users/* will aggregate data from all pages under /users/."
            >
                <LemonInput
                    size="small"
                    placeholder="https://www.example.com/*"
                    value={dataUrl ?? ''}
                    onChange={(value) => {
                        setDataUrl(value || null)
                    }}
                    fullWidth={true}
                />
                <div className="text-xs text-muted mt-1">Add * for wildcards to aggregate data from multiple pages</div>
                {dataUrl && !isBrowserUrlAuthorized ? <HeatmapsForbiddenURL /> : null}
            </SceneSection>
            <SceneDivider />
            <div className="flex gap-2">
                <LemonButton
                    className="w-fit"
                    type="primary"
                    data-attr="save-heatmap"
                    onClick={createHeatmap}
                    loading={false}
                    disabledReason={getDisabledReason()}
                >
                    Save
                </LemonButton>
            </div>
        </SceneContent>
    )
}
