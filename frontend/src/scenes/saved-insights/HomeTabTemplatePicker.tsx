import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { homeTabLogic } from './homeTabLogic'

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

export function HomeTabTemplatePicker(): JSX.Element {
    const { homeTabDashboardLoading, selectedTemplateKey } = useValues(homeTabLogic)
    const { createHomeTabDashboard } = useActions(homeTabLogic)

    return (
        <div className="flex justify-center py-12">
            <LemonCard className="w-full max-w-140" hoverEffect={false}>
                <div className="flex flex-col gap-1 mb-4">
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
                            onClick={() => createHomeTabDashboard({ templateKey, label })}
                            data-attr={`home-tab-template-${templateKey.toLowerCase().replace(/\s+/g, '-')}`}
                        >
                            {label}
                        </LemonButton>
                    ))}
                </div>
            </LemonCard>
        </div>
    )
}
