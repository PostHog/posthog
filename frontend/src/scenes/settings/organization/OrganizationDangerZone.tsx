import { useActions, useValues } from 'kea'
import { Dispatch, SetStateAction, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import type { OrganizationBasicType } from '~/types'

import { QuillDeleteOrganizationDialog } from './QuillDeleteOrganizationDialog'

export function DeleteOrganizationModal({
    isOpen,
    setIsOpen,
    organization,
    redirectPath,
}: {
    organization: OrganizationBasicType | null
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
    redirectPath?: string
}): JSX.Element | null {
    const { organizationBeingDeleted } = useValues(organizationLogic)
    const { deleteOrganization } = useActions(organizationLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const isDeletionInProgress = !!organization && organizationBeingDeleted === organization.id

    const close = (): void => setIsOpen(false)

    const handleDelete = organization
        ? () => deleteOrganization({ organizationId: organization.id, redirectPath })
        : undefined

    const handleConfirmationChange = (value: string): void => {
        if (organization) {
            setIsDeletionConfirmed(value.toLowerCase() === organization.name.toLowerCase())
        }
    }

    if (todayRailNav) {
        return (
            <QuillDeleteOrganizationDialog
                isOpen={isOpen}
                organization={organization}
                isDeletionConfirmed={isDeletionConfirmed}
                isDeletionInProgress={isDeletionInProgress}
                onClose={close}
                onConfirmationChange={handleConfirmationChange}
                onDelete={handleDelete}
            />
        )
    }

    return (
        <LemonModal
            title="Delete the entire organization?"
            onClose={!isDeletionInProgress ? close : undefined}
            footer={
                <>
                    <LemonButton disabled={isDeletionInProgress} type="secondary" onClick={close}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        status="danger"
                        disabled={!isDeletionConfirmed}
                        loading={isDeletionInProgress}
                        data-attr="delete-organization-ok"
                        onClick={handleDelete}
                    >{`Delete ${organization ? organization.name : 'the current organization'}`}</LemonButton>
                </>
            }
            isOpen={isOpen}
        >
            <p>
                Organization deletion <b>cannot be undone</b>. You will lose all data, <b>including all events</b>,
                related to all projects within this organization.
            </p>
            <p>
                Please type <strong>{organization ? organization.name : "this organization's name"}</strong> to confirm.
            </p>
            <LemonInput
                type="text"
                onChange={handleConfirmationChange}
                data-attr="delete-organization-confirmation-input"
            />
        </LemonModal>
    )
}

export function OrganizationDangerZone(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Owner,
        scope: RestrictionScope.Organization,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const deleteModal = currentOrganization && (
        <DeleteOrganizationModal
            isOpen={isModalVisible}
            setIsOpen={setIsModalVisible}
            organization={currentOrganization}
            redirectPath={urls.default()}
        />
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-2">
                {!restrictionReason && (
                    <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                        This deletes the organization, all its projects and all its data for every member. Your PostHog
                        account is not deleted. This is <b>irreversible</b>.
                    </Text>
                )}
                <Button
                    variant="destructive-outline"
                    onClick={() => setIsModalVisible(true)}
                    data-attr="delete-organization-button"
                    disabledReason={restrictionReason}
                >
                    <IconTrash />
                    <span>{`Delete ${currentOrganization?.name || 'the current organization'}`}</span>
                </Button>
                {deleteModal}
            </div>
        )
    }

    return (
        <>
            <div className="text-danger">
                {!restrictionReason && (
                    <p className="text-danger">
                        This deletes the organization, all its projects and all its data for every member. Your PostHog
                        account is not deleted. This is <b>irreversible</b>.
                    </p>
                )}
                <LemonButton
                    status="danger"
                    type="secondary"
                    onClick={() => setIsModalVisible(true)}
                    data-attr="delete-organization-button"
                    icon={<IconTrash />}
                    disabledReason={restrictionReason}
                >
                    Delete {currentOrganization?.name || 'the current organization'}
                </LemonButton>
            </div>
            {deleteModal}
        </>
    )
}
