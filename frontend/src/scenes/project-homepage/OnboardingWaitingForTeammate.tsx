import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { MailHog } from 'lib/components/hedgehogs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { UserType } from '~/types'

export function OnboardingWaitingForTeammate(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { loadUserSuccess } = useActions(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const [isCanceling, setIsCanceling] = useState(false)

    if (!user?.onboarding_delegated_to_invite || !currentOrganization?.id) {
        return null
    }

    const inviteId = user.onboarding_delegated_to_invite
    const orgId = currentOrganization.id

    const cancelDelegation = async (): Promise<void> => {
        if (isCanceling) {
            return
        }
        setIsCanceling(true)
        try {
            await api.delete(`api/organizations/${orgId}/invites/${inviteId}/`)
            // Refresh user state so the delegation pointer clears and sceneLogic stops
            // rendering this view.
            const freshUser = await api.get<UserType>('api/users/@me/')
            loadUserSuccess(freshUser)
            lemonToast.success('Delegation cancelled — you can finish setup yourself now.')
        } catch {
            lemonToast.error("Couldn't cancel the delegation. Please try again.")
        } finally {
            setIsCanceling(false)
        }
    }

    return (
        <SceneContent className="p-4">
            <div className="flex justify-center">
                <div className="max-w-xl w-full flex flex-col items-center gap-4 text-center py-8">
                    <MailHog className="w-32 h-24 object-contain" />
                    <h2 className="m-0">Waiting on your teammate</h2>
                    <p className="m-0 text-secondary">
                        We sent your teammate an invitation to finish setting up PostHog. They'll get admin access when
                        they accept — we'll let you know once they're in.
                    </p>
                    <div className="flex gap-2 mt-4">
                        <LemonButton
                            type="secondary"
                            onClick={cancelDelegation}
                            loading={isCanceling}
                            data-attr="onboarding-waiting-cancel-delegation"
                        >
                            Cancel and finish setup myself
                        </LemonButton>
                    </div>
                </div>
            </div>
        </SceneContent>
    )
}
