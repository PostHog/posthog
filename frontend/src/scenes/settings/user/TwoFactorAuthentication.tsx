import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconCheckmark, IconWarning } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { Setup2FA } from 'scenes/authentication/Setup2FA'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

export function TwoFactorAuthentication(): JSX.Element {
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { loadMembers } = useActions(membersLogic)
    const [modalVisible, setModalVisible] = useState(false)

    return (
        <div className="flex flex-col items-start">
            {modalVisible && (
                <LemonModal title="Set up or manage 2FA" onClose={() => setModalVisible(false)}>
                    <>
                        <b>
                            Use an authenticator app like Google Authenticator or 1Password to scan the QR code below.
                        </b>
                        <Setup2FA
                            onSuccess={() => {
                                setModalVisible(false)
                                updateUser({})
                                loadMembers()
                            }}
                        />
                    </>
                </LemonModal>
            )}

            {user?.is_2fa_enabled ? (
                <>
                    <div className="mb-2 flex items-center">
                        <IconCheckmark color="green" className="text-xl mr-2" />
                        <span className="font-medium">2FA enabled.</span>
                    </div>
                    <LemonButton type="primary" to="/account/two_factor/" targetBlank>
                        Manage or disable 2FA
                    </LemonButton>
                </>
            ) : (
                <div>
                    <div className="mb-2 flex items-center">
                        <IconWarning color="orange" className="text-xl mr-2" />
                        <span className="font-medium">2FA is not enabled.</span>
                    </div>
                    <LemonButton type="primary" onClick={() => setModalVisible(true)}>
                        Set up 2FA
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
