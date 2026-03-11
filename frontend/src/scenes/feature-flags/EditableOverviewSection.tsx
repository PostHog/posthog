import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'

interface EditableOverviewSectionProps {
    children: JSX.Element
    className?: string
    /** Override to disable editing for this section (e.g. experiment-linked flags) */
    disabledReason?: string
    /** Options passed to editFeatureFlag when the pencil is clicked */
    editOptions?: { expandAdvanced?: boolean }
}

export function EditableOverviewSection({
    children,
    className,
    disabledReason,
    editOptions,
}: EditableOverviewSectionProps): JSX.Element {
    const { featureFlag } = useValues(featureFlagLogic)
    const { editFeatureFlag } = useActions(featureFlagLogic)

    const canShowEditButton = !featureFlag.deleted

    return (
        <div className={`group relative rounded border p-4 bg-bg-light ${className ?? ''}`}>
            {canShowEditButton && (
                <div className="absolute top-3 right-3 z-10 opacity-0 transition-opacity group-hover:opacity-100">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.FeatureFlag}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={featureFlag.user_access_level}
                    >
                        {({ disabledReason: accessDisabledReason }) => (
                            <LemonButton
                                icon={<IconPencil />}
                                size="xsmall"
                                type="secondary"
                                disabledReason={disabledReason ?? accessDisabledReason}
                                onClick={() => editFeatureFlag(true, editOptions)}
                            />
                        )}
                    </AccessControlAction>
                </div>
            )}

            {children}
        </div>
    )
}
