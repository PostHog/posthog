import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { featureFlagLogic as featureFlagSceneLogic } from 'scenes/feature-flags/featureFlagLogic'

import { DEFAULT_TARGETING_FILTERS, productTourLogic } from '../productTourLogic'
import { AutoShowSection } from './AutoShowSection'
import { LinkedFlagField } from './LinkedFlagField'

export interface AutoShowModalProps {
    tourId: string
    isOpen: boolean
    onClose: () => void
}

export function AutoShowModal({ tourId, isOpen, onClose }: AutoShowModalProps): JSX.Element {
    const { productTour, targetingFlagFilters, hasCustomTargeting } = useValues(productTourLogic({ id: tourId }))
    const { setProductTourFormValue } = useActions(productTourLogic({ id: tourId }))

    const [showUserTargeting, setShowUserTargeting] = useState(hasCustomTargeting)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Auto-show settings"
            width={640}
            footer={
                <LemonButton type="primary" onClick={onClose}>
                    Done
                </LemonButton>
            }
        >
            <div className="space-y-6">
                {/* Who to show */}
                <div>
                    <h4 className="font-semibold mb-3">Who to show</h4>
                    <LemonSegmentedButton
                        size="small"
                        fullWidth
                        value={showUserTargeting ? 'conditions' : 'everyone'}
                        onChange={(value) => {
                            const showConditions = value === 'conditions'
                            setShowUserTargeting(showConditions)
                            if (!showConditions) {
                                setProductTourFormValue('targeting_flag_filters', DEFAULT_TARGETING_FILTERS)
                            }
                        }}
                        options={[
                            { value: 'everyone', label: 'All users' },
                            { value: 'conditions', label: 'Matching conditions' },
                        ]}
                    />
                    {showUserTargeting && (
                        <div className="mt-3 border border-dashed rounded p-3">
                            <BindLogic
                                logic={featureFlagSceneLogic}
                                props={{
                                    id: productTour?.internal_targeting_flag?.id
                                        ? String(productTour.internal_targeting_flag.id)
                                        : 'new',
                                }}
                            >
                                <FeatureFlagReleaseConditions
                                    id={
                                        productTour?.internal_targeting_flag?.id
                                            ? String(productTour.internal_targeting_flag.id)
                                            : 'new'
                                    }
                                    excludeTitle={true}
                                    hideMatchOptions={true}
                                    filters={targetingFlagFilters || DEFAULT_TARGETING_FILTERS}
                                    onChange={(filters) => {
                                        setProductTourFormValue('targeting_flag_filters', filters)
                                    }}
                                />
                            </BindLogic>
                        </div>
                    )}
                    <LinkedFlagField id={tourId} />
                </div>

                {/* Where, when, how often */}
                <AutoShowSection id={tourId} />
            </div>
        </LemonModal>
    )
}
