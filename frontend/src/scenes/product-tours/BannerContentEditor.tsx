import { JSONContent } from '@tiptap/core'

import { LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { ProductTourAppearance, ProductTourBannerConfig, ProductTourStep } from '~/types'

import { BannerPreviewWrapper } from './components/ProductTourPreview'
import { TourSelector } from './components/TourSelector'
import { StepContentEditor } from './editor/StepContentEditor'

export interface BannerContentEditorProps {
    step: ProductTourStep | undefined
    appearance: ProductTourAppearance | undefined
    onChange: (step: ProductTourStep) => void
}

export function BannerContentEditor({ step, appearance, onChange }: BannerContentEditorProps): JSX.Element {
    const updateStep = (updates: Partial<ProductTourStep>): void => {
        if (step) {
            onChange({ ...step, ...updates })
        }
    }

    if (!step) {
        return <div>No content</div>
    }

    const behavior = step.bannerConfig?.behavior ?? 'sticky'
    const actionType = step.bannerConfig?.action?.type ?? 'none'

    const updateBannerConfig = (updates: Partial<ProductTourBannerConfig>): void => {
        updateStep({
            bannerConfig: {
                ...step.bannerConfig,
                behavior,
                ...updates,
            },
        })
    }

    const updateAction = (updates: Partial<NonNullable<ProductTourBannerConfig['action']>>): void => {
        updateBannerConfig({
            action: {
                ...step.bannerConfig?.action,
                type: actionType,
                ...updates,
            },
        })
    }

    return (
        <div className="space-y-6">
            {/* Full-width preview */}
            <BannerPreviewWrapper step={step} appearance={appearance} />

            {/* Editor and settings */}
            <div className="flex gap-8">
                <div className="flex-1 min-w-0">
                    <label className="text-sm font-medium block mb-2">Banner message</label>
                    <StepContentEditor
                        content={step.content as JSONContent | null}
                        onChange={(content) => updateStep({ content })}
                        placeholder="Your banner message here..."
                        inlineOnly
                    />
                </div>

                <div className="flex-1 min-w-0 space-y-4">
                    <div>
                        <label className="text-sm font-medium block mb-3">Settings</label>
                        <div className="space-y-3">
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className="font-medium text-sm">Position</div>
                                    <div className="text-muted text-xs">
                                        {behavior === 'sticky'
                                            ? 'Top of page, stays visible while scrolling'
                                            : behavior === 'static'
                                              ? 'Top of page, scrolls with content'
                                              : 'Injected into your container element'}
                                    </div>
                                </div>
                                <LemonSegmentedButton
                                    size="small"
                                    value={behavior}
                                    onChange={(value) =>
                                        updateBannerConfig({
                                            behavior: value as ProductTourBannerConfig['behavior'],
                                            selector: value === 'custom' ? step.bannerConfig?.selector : undefined,
                                        })
                                    }
                                    options={[
                                        { value: 'sticky', label: 'Sticky' },
                                        { value: 'static', label: 'Static' },
                                        { value: 'custom', label: 'Custom' },
                                    ]}
                                />
                            </div>
                            {behavior === 'custom' && (
                                <LemonInput
                                    value={step.bannerConfig?.selector ?? ''}
                                    onChange={(selector) => updateBannerConfig({ selector })}
                                    placeholder="#my-banner-container"
                                    size="small"
                                    fullWidth
                                />
                            )}
                        </div>
                    </div>

                    <div className="pt-4 border-t">
                        <label className="text-sm font-medium block mb-3">Click action</label>
                        <div className="space-y-3">
                            <LemonSelect
                                value={actionType}
                                onChange={(value) =>
                                    updateAction({
                                        type: value as NonNullable<ProductTourBannerConfig['action']>['type'],
                                        link: value === 'link' ? step.bannerConfig?.action?.link : undefined,
                                        tourId:
                                            value === 'trigger_tour' ? step.bannerConfig?.action?.tourId : undefined,
                                    })
                                }
                                options={[
                                    { value: 'none', label: 'None' },
                                    { value: 'link', label: 'Open link' },
                                    { value: 'trigger_tour', label: 'Start tour' },
                                ]}
                                size="small"
                                fullWidth
                            />
                            {actionType === 'link' && (
                                <LemonInput
                                    value={step.bannerConfig?.action?.link ?? ''}
                                    onChange={(link) => updateAction({ link })}
                                    placeholder="https://example.com"
                                    size="small"
                                    fullWidth
                                />
                            )}
                            {actionType === 'trigger_tour' && (
                                <TourSelector
                                    value={step.bannerConfig?.action?.tourId}
                                    onChange={(tourId) => updateAction({ tourId })}
                                    fullWidth
                                />
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
