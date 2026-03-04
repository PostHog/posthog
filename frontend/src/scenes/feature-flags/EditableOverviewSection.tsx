import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonDialog, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FeatureFlagEditableSection, featureFlagLogic } from './featureFlagLogic'

interface EditableOverviewSectionProps {
    section: FeatureFlagEditableSection
    children: (props: { isEditing: boolean }) => JSX.Element
    className?: string
    /** Override to disable editing for this section (e.g. experiment-linked flags) */
    disabledReason?: string
}

export function EditableOverviewSection({
    section,
    children,
    className,
    disabledReason,
}: EditableOverviewSectionProps): JSX.Element {
    const { featureFlag, editingSection, sectionDraft, featureFlagLoading } = useValues(featureFlagLogic)
    const { setSectionEditing, cancelSectionEdit, saveSectionEdit } = useActions(featureFlagLogic)

    const isEditing = editingSection === section
    const anotherSectionEditing = editingSection !== null && editingSection !== section
    const canShowEditButton = !featureFlag.deleted && !anotherSectionEditing

    const handleCancel = (): void => {
        if (sectionDraft) {
            LemonDialog.open({
                title: 'Discard changes?',
                description: 'You have unsaved changes that will be lost.',
                primaryButton: {
                    children: 'Discard',
                    status: 'danger',
                    onClick: cancelSectionEdit,
                },
                secondaryButton: {
                    children: 'Keep editing',
                },
            })
        } else {
            cancelSectionEdit()
        }
    }

    return (
        <div
            className={`group relative rounded border p-4 bg-bg-light transition-colors ${
                !isEditing && canShowEditButton && !disabledReason ? 'hover:border-primary/30' : ''
            } ${className ?? ''}`}
        >
            {!isEditing && canShowEditButton && (
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
                                onClick={() => setSectionEditing(section)}
                            />
                        )}
                    </AccessControlAction>
                </div>
            )}

            {children({ isEditing })}

            {isEditing && (
                <div className="flex justify-end gap-2 mt-3 pt-3 border-t border-border-light">
                    <LemonButton type="secondary" size="small" disabled={featureFlagLoading} onClick={handleCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        disabled={featureFlagLoading}
                        icon={featureFlagLoading ? <Spinner textColored /> : undefined}
                        onClick={saveSectionEdit}
                    >
                        Save
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
