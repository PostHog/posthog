import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { ProductTourBannerConfig } from '~/types'

import { TourSelector } from '../components/TourSelector'
import { productTourLogic } from '../productTourLogic'

export interface BannerSettingsPanelProps {
    tourId: string
}

export function BannerSettingsPanel({ tourId }: BannerSettingsPanelProps): JSX.Element {
    const { productTourForm, selectedStepIndex } = useValues(productTourLogic({ id: tourId }))
    const { updateSelectedStep } = useActions(productTourLogic({ id: tourId }))

    const steps = productTourForm.content?.steps ?? []
    const step = steps[selectedStepIndex]

    const behavior = step.bannerConfig?.behavior ?? 'sticky'
    const actionType = step.bannerConfig?.action?.type ?? 'none'

    const updateBannerConfig = (updates: Partial<ProductTourBannerConfig>): void => {
        updateSelectedStep({
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
        <div className="py-3 px-4">
            <div className="flex gap-10">
                <div className="flex-1 min-w-0 space-y-4">
                    <div className="flex items-center justify-between gap-4">
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

                <div className="flex-1 min-w-0 space-y-3">
                    <div className="font-medium text-sm">Click action</div>
                    <LemonSelect
                        value={actionType}
                        onChange={(value) =>
                            updateAction({
                                type: value as NonNullable<ProductTourBannerConfig['action']>['type'],
                                link: value === 'link' ? step.bannerConfig?.action?.link : undefined,
                                tourId: value === 'trigger_tour' ? step.bannerConfig?.action?.tourId : undefined,
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
    )
}
