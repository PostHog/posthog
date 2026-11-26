import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { fullNameOrEmail } from 'lib/utils/strings'
import { canLogInAsFromCurrentOrigin, getUserLogInAsUrl } from 'lib/utils/userAdmin'
import { urls } from 'scenes/urls'

import { adminLoginAs } from '~/layout/navigation/ImpersonationNotice/adminLoginAs'
import { ImpersonationReasonModal } from '~/layout/navigation/ImpersonationNotice/ImpersonationReasonModal'
import { ImpersonationSessionUncertainError } from '~/layout/navigation/ImpersonationNotice/ImpersonationSessionUncertainError'

import type { AccountOrganizationMember } from './accountRelatedUsersLogic'
import { AccountsEvents } from './constants'

export function AccountMemberImpersonateButton({ member }: { member: AccountOrganizationMember }): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [readOnly, setReadOnly] = useState(true)
    const [isLoggingIn, setIsLoggingIn] = useState(false)

    if (member.source !== 'api' || !canLogInAsFromCurrentOrigin(member.region)) {
        return (
            <LemonButton
                type="secondary"
                size="xsmall"
                to={getUserLogInAsUrl(member.region, member.user.id)}
                targetBlank
                tooltip={`Confirm this user's identity and log in as them in ${member.region} PostHog Admin.`}
                data-attr="customer-analytics-account-user-admin-link"
                onClick={() => posthog.capture(AccountsEvents.RelatedUserAdminOpened, { region: member.region })}
            >
                Impersonate
            </LemonButton>
        )
    }

    const logIn = async (reason: string): Promise<void> => {
        setIsLoggingIn(true)
        try {
            await adminLoginAs({ userId: member.user.id, reason, readOnly })
            posthog.capture(AccountsEvents.RelatedUserImpersonated, {
                region: member.region,
                read_only: readOnly,
            })
            // A full page load resets org, project and scene state for the impersonated user, who can't open this account.
            window.location.assign(urls.default())
        } catch (error) {
            posthog.captureException(error as Error, { scope: 'AccountMemberImpersonateButton.logIn' })
            if (error instanceof ImpersonationSessionUncertainError) {
                window.location.assign(urls.default())
                return
            }
            lemonToast.error(error instanceof Error ? error.message : 'Could not log in as this user. Try again.')
            setIsLoggingIn(false)
        }
    }

    return (
        <>
            <LemonButton
                type="secondary"
                size="xsmall"
                tooltip="Log in as this user."
                data-attr="customer-analytics-account-user-admin-link"
                onClick={() => {
                    setReadOnly(true)
                    setIsModalOpen(true)
                }}
            >
                Impersonate
            </LemonButton>
            <ImpersonationReasonModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                onConfirm={logIn}
                loading={isLoggingIn}
                title={`Log in as ${fullNameOrEmail(member.user)}`}
                description="You see PostHog as this user until you log out or the session times out."
                confirmText="Log in"
            >
                <LemonCheckbox checked={readOnly} onChange={setReadOnly} label="Read-only mode (recommended)" />
            </ImpersonationReasonModal>
        </>
    )
}
