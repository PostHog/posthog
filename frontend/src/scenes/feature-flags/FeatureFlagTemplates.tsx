import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconPeople, IconRocket, IconShield } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

import { userLogic } from '../userLogic'
import { featureFlagLogic } from './featureFlagLogic'

interface TemplateValues {
    key?: string
    name?: string
    active?: boolean
    filters?: FeatureFlagType['filters']
}

interface FlagTemplate {
    id: string
    name: string
    description: string
    icon: React.ReactNode
    getValues: (currentFlag: FeatureFlagType) => TemplateValues
}

interface FeatureFlagTemplatesProps {
    onTemplateApplied?: (sectionsToOpen: string[]) => void
}

export function FeatureFlagTemplates({ onTemplateApplied }: FeatureFlagTemplatesProps): JSX.Element {
    const { featureFlag, featureFlagLoading, userEditedFields } = useValues(featureFlagLogic)
    const { setFeatureFlag } = useActions(featureFlagLogic)
    const { user } = useValues(userLogic)

    const applyTemplate = (template: FlagTemplate): void => {
        // Read featureFlag fresh from the logic to avoid stale closures
        const currentFlag = featureFlag
        if (!currentFlag) {
            return
        }
        const templateValues = template.getValues(currentFlag)
        const preservedFields: string[] = []
        const updates: Partial<FeatureFlagType> = { ...currentFlag }

        if (templateValues.key !== undefined) {
            if (userEditedFields.has('key')) {
                preservedFields.push('flag key')
            } else {
                updates.key = currentFlag.key || templateValues.key
            }
        }

        if (templateValues.name !== undefined) {
            if (userEditedFields.has('name')) {
                preservedFields.push('description')
            } else {
                updates.name = currentFlag.name || templateValues.name
            }
        }

        if (templateValues.active !== undefined) {
            if (userEditedFields.has('active')) {
                preservedFields.push('enabled state')
            } else {
                updates.active = templateValues.active
            }
        }

        if (templateValues.filters !== undefined) {
            if (userEditedFields.has('filters')) {
                preservedFields.push('release conditions')
            } else {
                updates.filters = {
                    ...currentFlag.filters,
                    ...templateValues.filters,
                }
            }
        }

        setFeatureFlag(updates as FeatureFlagType)

        if (preservedFields.length > 0) {
            lemonToast.info(
                `Template applied: ${template.name}. Your ${preservedFields.join(', ')} ${preservedFields.length === 1 ? 'was' : 'were'} preserved.`
            )
        } else {
            lemonToast.success(`Template applied: ${template.name}`)
        }
        onTemplateApplied?.(['basics', 'targeting'])
    }

    if (!featureFlag) {
        return <></>
    }

    // Don't allow template application while the flag is still loading
    // to prevent race conditions where the loader overwrites template values
    const isLoading = featureFlagLoading

    const emailDomain = user?.email?.split('@')[1] || 'example.com'

    const templates: FlagTemplate[] = [
        {
            id: 'percentage-rollout',
            name: '% Rollout',
            description: 'Gradually roll out to a percentage of users',
            icon: <IconRocket className="text-2xl" />,
            getValues: (flag) => ({
                key: 'gradual-rollout',
                filters: {
                    ...flag.filters,
                    groups: [{ properties: [], rollout_percentage: 20, variant: null }],
                },
            }),
        },
        {
            id: 'internal-only',
            name: 'Internal Only',
            description: 'Only your team can see this',
            icon: <IconShield className="text-2xl" />,
            getValues: (flag) => ({
                key: 'internal-only',
                filters: {
                    ...flag.filters,
                    groups: [
                        {
                            properties: [
                                {
                                    key: 'email',
                                    type: PropertyFilterType.Person,
                                    value: `@${emailDomain}`,
                                    operator: PropertyOperator.IContains,
                                },
                            ],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            }),
        },
        {
            id: 'beta-users',
            name: 'Beta Users',
            description: 'Target users with a beta property',
            icon: <IconPeople className="text-2xl" />,
            getValues: (flag) => ({
                key: 'beta-feature',
                filters: {
                    ...flag.filters,
                    groups: [
                        {
                            properties: [
                                {
                                    key: 'beta',
                                    type: PropertyFilterType.Person,
                                    value: ['true'],
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                            rollout_percentage: 100,
                            variant: null,
                        },
                    ],
                },
            }),
        },
        {
            id: 'kill-switch',
            name: 'Kill Switch',
            description: 'Quick on/off for incidents',
            icon: <IconCheckCircle className="text-2xl" />,
            getValues: (flag) => ({
                key: 'kill-switch',
                name: 'Emergency kill switch for…',
                active: true,
                filters: {
                    ...flag.filters,
                    groups: [{ properties: [], rollout_percentage: 100, variant: null }],
                },
            }),
        },
    ]

    return (
        <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
                <h3 className="mb-0 text-sm font-semibold">Start with a template</h3>
            </div>
            <div className="flex gap-3 overflow-x-auto">
                {templates.map((template) => (
                    <LemonButton
                        key={template.id}
                        type="secondary"
                        onClick={() => applyTemplate(template)}
                        disabledReason={isLoading ? 'Loading flag data…' : undefined}
                        className="flex-shrink-0 w-36 !h-auto !items-start"
                    >
                        <div className="flex flex-col text-left py-1">
                            <div className="text-muted mb-2">{template.icon}</div>
                            <div className="font-semibold text-sm mb-1">{template.name}</div>
                            <div className="text-xs text-muted whitespace-normal">{template.description}</div>
                        </div>
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
