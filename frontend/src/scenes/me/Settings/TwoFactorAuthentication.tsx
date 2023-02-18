import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { IconCheckmark, IconWarning } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { Setup2FA } from 'scenes/authentication/Setup2FA'

export function TwoFactorAuthentication(): JSX.Element {
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const [modalVisible, setModalVisible] = useState(false)

    return (
        <div>
            {modalVisible && (
                <LemonModal title="Set up or manage 2FA" onClose={() => setModalVisible(false)}>
                    <Setup2FA
                        onSuccess={() => {
                            setModalVisible(false)
                            updateUser({})
                        }}
                    />
                </LemonModal>
            )}

            {user.is_2fa_enabled ? (
                <>
                    <IconCheckmark color="green" />
                    2FA enabled.
                    <br />
                    <br />
                    <LemonButton type="primary" to="/account/two_factor/" targetBlank={true} style={{ width: 180 }}>
                        Manage or disable 2FA
                    </LemonButton>
                </>
            ) : (
                <>
                    <IconWarning color="orange" />
                    2FA is not enabled.
                    <br />
                    <br />
                    <LemonButton type="primary" onClick={() => setModalVisible(true)}>
                        Set up 2FA
                    </LemonButton>
                </>
            )}
        </div>
    )
}
