import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconPeople, IconRocket, IconShield } from '@posthog/icons'


import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { userLogic } from '../userLogic'
import { featureFlagLogic } from './featureFlagLogic'

interface FlagTemplate {
    id: string
    name: string
    description: string
    icon: React.ReactNode
    applyTemplate: () => void
}

interface FeatureFlagTemplatesProps {
    onTemplateApplied?: (sectionsToOpen: string[]) => void
}

export function FeatureFlagTemplates({ onTemplateApplied }: FeatureFlagTemplatesProps): JSX.Element {
    const { featureFlag } = useValues(featureFlagLogic)
    const { setFeatureFlag } = useActions(featureFlagLogic)
    const { user } = useValues(userLogic)

    // Safety check - if featureFlag is not loaded yet, show nothing
    if (!featureFlag) {
        return <div>Loading...</div>
    }

    const templates: FlagTemplate[] = [
        {
            id: 'percentage-rollout',
            name: '% Rollout',
            description: 'Gradually roll out to a percentage of users',
            icon: <IconRocket className="text-2xl" />,
            applyTemplate: () => {
                setFeatureFlag({
                    ...featureFlag,
                    filters: {
                        ...featureFlag.filters,
                        groups: [
                            {
                                properties: [],
                                rollout_percentage: 20,
                                variant: null,
                            },
                        ],
                    },
                })
                lemonToast.success('Template applied: % Rollout')
                onTemplateApplied?.(['basics', 'targeting'])
            },
        },
        {
            id: 'internal-only',
            name: 'Internal Only',
            description: 'Only your team can see this',
            icon: <IconShield className="text-2xl" />,
            applyTemplate: () => {
                const emailDomain = user?.email?.split('@')[1] || 'example.com'
                setFeatureFlag({
                    ...featureFlag,
                    filters: {
                        ...featureFlag.filters,
                        groups: [
                            {
                                properties: [
                                    {
                                        key: 'email',
                                        type: 'person',
                                        value: `@${emailDomain}`,
                                        operator: 'icontains',
                                    },
                                ],
                                rollout_percentage: 100,
                                variant: null,
                            },
                        ],
                    },
                })
                lemonToast.success('Template applied: Internal Only')
                onTemplateApplied?.(['basics', 'targeting'])
            },
        },
        {
            id: 'beta-users',
            name: 'Beta Users',
            description: 'Target users with a beta property',
            icon: <IconPeople className="text-2xl" />,
            applyTemplate: () => {
                setFeatureFlag({
                    ...featureFlag,
                    filters: {
                        ...featureFlag.filters,
                        groups: [
                            {
                                properties: [
                                    {
                                        key: 'beta',
                                        type: 'person',
                                        value: ['true'],
                                        operator: 'exact',
                                    },
                                ],
                                rollout_percentage: 100,
                                variant: null,
                            },
                        ],
                    },
                })
                lemonToast.success('Template applied: Beta Users')
                onTemplateApplied?.(['basics', 'targeting'])
            },
        },
        {
            id: 'kill-switch',
            name: 'Kill Switch',
            description: 'Quick on/off for incidents',
            icon: <IconCheckCircle className="text-2xl" />,
            applyTemplate: () => {
                setFeatureFlag({
                    ...featureFlag,
                    name: featureFlag.name || 'Emergency kill switch for...',
                    active: true,
                    filters: {
                        ...featureFlag.filters,
                        groups: [
                            {
                                properties: [],
                                rollout_percentage: 100,
                                variant: null,
                            },
                        ],
                    },
                })
                lemonToast.success('Template applied: Kill Switch')
                onTemplateApplied?.(['basics', 'targeting'])
            },
        },
    ]

    return (
        <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
                <h3 className="mb-0 text-sm font-semibold">Start with a template</h3>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-2">
                {templates.map((template) => (
                    <button
                        key={template.id}
                        onClick={template.applyTemplate}
                        className="flex-shrink-0 border rounded-lg p-4 w-36 hover:border-primary-light hover:bg-primary-highlight transition-all cursor-pointer text-left"
                    >
                        <div className="text-muted mb-2">{template.icon}</div>
                        <div className="font-semibold text-sm mb-1">{template.name}</div>
                        <div className="text-xs text-muted">{template.description}</div>
                    </button>
                ))}
            </div>
        </div>
    )
}
