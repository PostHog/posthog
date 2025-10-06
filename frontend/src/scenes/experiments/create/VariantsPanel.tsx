import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { match } from 'ts-pattern'

import { LemonButton, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { SelectableCard } from '~/scenes/experiments/components/SelectableCard'
import type { Experiment, FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { VariantsPanelCreateFeatureFlag } from './VariantsPanelCreateFeatureFlag'
import { VariantsPanelLinkFeatureFlag } from './VariantsPanelLinkFeatureFlag'
import { variantsPanelLogic } from './variantsPanelLogic'

interface VariantsPanelProps {
    experiment: Experiment
    onChange: (updates: {
        feature_flag_key?: string
        parameters?: {
            feature_flag_variants?: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
        }
    }) => void
}

const SelectExistingFeatureFlagModal = ({
    isOpen,
    onClose,
    onSelect,
}: {
    isOpen: boolean
    onClose: () => void
    onSelect: (flag: FeatureFlagType) => void
}): JSX.Element => {
    const [search, setSearch] = useState('')
    const { availableFeatureFlags, availableFeatureFlagsLoading } = useValues(variantsPanelLogic)
    const { searchFeatureFlags, resetFeatureFlagsSearch, loadAllEligibleFeatureFlags } = useActions(variantsPanelLogic)

    useEffect(() => {
        // Load all eligible feature flags when modal opens
        loadAllEligibleFeatureFlags()
    }, [loadAllEligibleFeatureFlags])

    useEffect(() => {
        if (search) {
            searchFeatureFlags(search)
        } else {
            // If search is cleared, reload all flags
            loadAllEligibleFeatureFlags()
        }
    }, [search, loadAllEligibleFeatureFlags, searchFeatureFlags])

    const handleClose = (): void => {
        resetFeatureFlagsSearch()
        setSearch('')
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="Choose an existing feature flag" width="50%">
            <div className="space-y-2">
                <div className="text-muted mb-2 max-w-xl">
                    Select an existing multivariate feature flag to use with this experiment. The feature flag must use
                    multiple variants with <code>'control'</code> as the first, and not be associated with an existing
                    experiment.
                </div>
                <div className="mb-4">
                    <LemonInput
                        type="search"
                        placeholder="Search for feature flags"
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                </div>
                <LemonTable
                    dataSource={availableFeatureFlags}
                    loading={availableFeatureFlagsLoading}
                    columns={[
                        {
                            title: 'Key',
                            dataIndex: 'key',
                            render: (key, flag) => (
                                <div className="flex items-center">
                                    <div className="font-semibold">{key}</div>
                                    <Link
                                        to={urls.featureFlag(flag.id as number)}
                                        target="_blank"
                                        className="flex items-center"
                                    >
                                        <IconOpenInNew className="ml-1" />
                                    </Link>
                                </div>
                            ),
                        },
                        {
                            title: 'Name',
                            dataIndex: 'name',
                        },
                        {
                            title: null,
                            render: function RenderActions(_, flag) {
                                return (
                                    <div className="flex items-center justify-end">
                                        <LemonButton
                                            size="xsmall"
                                            type="primary"
                                            onClick={() => {
                                                onSelect(flag)
                                                handleClose()
                                            }}
                                        >
                                            Select
                                        </LemonButton>
                                    </div>
                                )
                            },
                        },
                    ]}
                    emptyState="No feature flags match your search. Try different keywords."
                />
            </div>
        </LemonModal>
    )
}

export function VariantsPanel({ experiment, onChange }: VariantsPanelProps): JSX.Element {
    // we'll use local state to handle selectors and modals
    const [flagSourceMode, setFlagSourceMode] = useState<'create' | 'link'>('create')
    const [linkedFeatureFlag, setLinkedFeatureFlag] = useState<FeatureFlagType | null>(null)
    const [showFeatureFlagSelector, setShowFeatureFlagSelector] = useState(false)
    // Store the created key separately to preserve it when switching modes

    return (
        <div className="space-y-6">
            {/* Feature Flag Source Selection */}
            <div>
                <h3 className="font-semibold mb-3">Feature Flag Configuration</h3>
                <div className="flex gap-4 mb-6">
                    <SelectableCard
                        title="Create new feature flag"
                        description="Generate a new feature flag with custom variants for this experiment."
                        selected={flagSourceMode === 'create'}
                        onClick={() => {
                            setFlagSourceMode('create')
                        }}
                    />
                    <SelectableCard
                        title="Link existing feature flag"
                        description="Use an existing multivariate feature flag and inherit its variants."
                        selected={flagSourceMode === 'link'}
                        onClick={() => setFlagSourceMode('link')}
                    />
                </div>
            </div>

            {match(flagSourceMode)
                .with('create', () => <VariantsPanelCreateFeatureFlag experiment={experiment} onChange={onChange} />)
                .with('link', () => (
                    <VariantsPanelLinkFeatureFlag
                        linkedFeatureFlag={linkedFeatureFlag}
                        setShowFeatureFlagSelector={setShowFeatureFlagSelector}
                    />
                ))
                .exhaustive()}

            {/* Feature Flag Selection Modal */}
            <SelectExistingFeatureFlagModal
                isOpen={showFeatureFlagSelector}
                onClose={() => setShowFeatureFlagSelector(false)}
                onSelect={(flag) => {
                    setLinkedFeatureFlag(flag)
                    setShowFeatureFlagSelector(false)
                }}
            />
        </div>
    )
}
