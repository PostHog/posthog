import { useActions, useValues } from 'kea'
import { useState } from 'react'

import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonButton, LemonCard, LemonTextArea } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { homeTabLogic } from './homeTabLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlass)

interface TemplateOption {
    label: string
    templateKey: string
}

const TEMPLATE_OPTIONS: TemplateOption[] = [
    { label: 'SaaS or B2B software', templateKey: 'SaaS product' },
    { label: 'E-commerce or online store', templateKey: 'E-commerce' },
    { label: 'Mobile app', templateKey: 'Mobile app' },
    { label: 'Something else', templateKey: 'Product analytics' },
]

const FREE_TEXT_SUBMIT_KEY = '__free_text__'

export function HomeTabTemplatePicker(): JSX.Element {
    const { homeTabDashboardLoading, selectedTemplateKey } = useValues(homeTabLogic)
    const { createHomeTabDashboard } = useActions(homeTabLogic)
    const [freeText, setFreeText] = useState('')
    const trimmedFreeText = freeText.trim()

    return (
        <div className="flex justify-center py-12">
            <LemonCard className="w-full max-w-140" hoverEffect={false}>
                <div className="flex flex-col items-center gap-1 mb-4 text-center">
                    <HedgehogMagnifyingGlass className="w-24 mb-2" loading="eager" />
                    <h2 className="mb-0">What does your product do?</h2>
                    <p className="text-secondary mb-0">
                        We'll set up your Home tab with a dashboard that fits, built from events you're already sending.
                    </p>
                </div>
                <div className="flex flex-col gap-2">
                    {TEMPLATE_OPTIONS.map(({ label, templateKey }) => (
                        <LemonButton
                            key={templateKey}
                            type="secondary"
                            fullWidth
                            center
                            size="large"
                            loading={homeTabDashboardLoading && selectedTemplateKey === templateKey}
                            disabledReason={
                                homeTabDashboardLoading && selectedTemplateKey !== templateKey
                                    ? 'Setting up your Home tab dashboard'
                                    : undefined
                            }
                            onClick={() => createHomeTabDashboard({ templateKey, label, freeText: trimmedFreeText })}
                            data-attr={`home-tab-template-${templateKey.toLowerCase().replace(/\s+/g, '-')}`}
                        >
                            {label}
                        </LemonButton>
                    ))}
                </div>
                <div className="flex flex-col gap-2 mt-4 pt-4 border-t">
                    <p className="text-secondary mb-0">
                        Or describe your product and we'll find the best fit — or have PostHog AI build one for you.
                    </p>
                    <LemonTextArea
                        placeholder="e.g. a marketplace connecting freelance designers with small businesses"
                        value={freeText}
                        onChange={setFreeText}
                        minRows={2}
                        data-attr="home-tab-template-free-text"
                    />
                    <LemonButton
                        type="primary"
                        fullWidth
                        center
                        disabledReason={trimmedFreeText ? undefined : 'Describe your product first'}
                        loading={homeTabDashboardLoading && selectedTemplateKey === FREE_TEXT_SUBMIT_KEY}
                        onClick={() =>
                            createHomeTabDashboard({
                                templateKey: FREE_TEXT_SUBMIT_KEY,
                                label: trimmedFreeText.slice(0, 100),
                                freeText: trimmedFreeText,
                            })
                        }
                        data-attr="home-tab-template-free-text-submit"
                    >
                        Continue
                    </LemonButton>
                </div>
            </LemonCard>
        </div>
    )
}
