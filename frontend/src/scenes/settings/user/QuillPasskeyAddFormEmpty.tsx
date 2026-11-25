import { useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { passkeySettingsLogic } from './passkeySettingsLogic'
import { QuillPasskeyRegistrationBanners } from './QuillPasskeyRegistrationBanners'

export function QuillPasskeyAddFormEmpty({
    isRegistering,
    onAddPasskey,
}: {
    isRegistering: boolean
    onAddPasskey: () => void
}): JSX.Element {
    const { registrationStep } = useValues(passkeySettingsLogic)

    return (
        <div className="flex flex-col items-start gap-4">
            <QuillPasskeyRegistrationBanners />
            <Text size="xs" variant="muted" render={<p className="m-0 max-w-lg" />}>
                Passkeys provide a faster, more seamless sign-in experience. Use your device's biometric authentication
                or a security key to sign in without passwords.
            </Text>
            <Button
                variant="primary"
                onClick={onAddPasskey}
                loading={isRegistering}
                disabledReason={isRegistering ? 'Registration in progress...' : undefined}
            >
                {registrationStep === 'verifying' ? 'Verifying...' : 'Add passkey'}
            </Button>
        </div>
    )
}
