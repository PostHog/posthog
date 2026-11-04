import { useActions, useValues } from 'kea'

import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { BeginPasskeyLoginParams, passkeyLogic } from './passkeyLogic'

interface PasskeyLoginButtonProps {
    isLastUsed?: boolean
    extraQueryParams?: Record<string, string>
}

export function PasskeyLoginButton({ isLastUsed, extraQueryParams }: PasskeyLoginButtonProps): JSX.Element {
    const { beginPasskeyLogin } = useActions(passkeyLogic)
    const { isLoading } = useValues(passkeyLogic)

    return (
        <div className="relative">
            <LemonButton
                size="large"
                icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-7 h-7" />}
                active={isLastUsed}
                tooltip="Passkey"
                htmlType="button"
                onClick={() => {
                    beginPasskeyLogin(undefined, extraQueryParams as BeginPasskeyLoginParams)
                }}
                loading={isLoading}
                data-attr="passkey-login"
            />
            {isLastUsed && (
                <LemonTag
                    type="muted"
                    size="small"
                    className="absolute -top-3 left-1/2 -translate-x-1/2 pointer-events-none"
                >
                    Last used
                </LemonTag>
            )}
        </div>
    )
}
