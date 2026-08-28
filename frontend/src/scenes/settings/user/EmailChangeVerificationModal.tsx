import { useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'

import { pngHoggie } from 'lib/brand/hoggies'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { isValidVerificationCode } from 'scenes/authentication/shared/verificationCode'
import { VerificationCodeInput } from 'scenes/authentication/shared/VerificationCodeInput'
import { userLogic } from 'scenes/userLogic'

import { MAX_RESENDS, emailChangeVerificationLogic } from './emailChangeVerificationLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function EmailChangeVerificationModal(): JSX.Element {
    const {
        modalOpen,
        verificationCode,
        verificationCodeError,
        verificationResultLoading,
        resendResultLoading,
        resendCooldown,
        resendsUsed,
    } = useValues(emailChangeVerificationLogic)
    const { closeModal, setVerificationCode, submitVerificationCode, resendCode } =
        useActions(emailChangeVerificationLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { user } = useValues(userLogic)

    return (
        <LemonModal isOpen={modalOpen} onClose={closeModal} simple width={480}>
            <form
                className="flex flex-col items-center gap-2.5 p-6 text-center"
                onSubmit={(e) => {
                    e.preventDefault()
                    if (!verificationResultLoading) {
                        submitVerificationCode()
                    }
                }}
            >
                <HedgehogMagnifyingGlass className="block w-auto mx-auto h-28" />
                <h2 className="m-0 text-2xl font-bold">Check your inbox</h2>
                <p className="m-0 mb-2 text-secondary text-pretty">
                    We emailed a 6-digit code to <strong>{user?.pending_email}</strong>. The code is valid for 30
                    minutes.
                </p>
                <VerificationCodeInput
                    autoFocus
                    value={verificationCode}
                    onChange={setVerificationCode}
                    error={verificationCodeError}
                    disabled={verificationResultLoading}
                    data-attr="email-change-verification-code"
                />
                <LemonButton
                    type="primary"
                    size="large"
                    center
                    fullWidth
                    htmlType="submit"
                    loading={verificationResultLoading}
                    disabledReason={
                        isValidVerificationCode(verificationCode) ? undefined : 'Enter the 6-digit code from your email'
                    }
                    data-attr="email-change-verification-submit"
                >
                    Verify email
                </LemonButton>
                {resendsUsed < MAX_RESENDS ? (
                    <LemonButton
                        size="small"
                        center
                        loading={resendResultLoading}
                        disabledReason={resendCooldown > 0 ? `You can resend in ${resendCooldown}s` : undefined}
                        onClick={resendCode}
                        data-attr="email-change-verification-resend"
                    >
                        Not seeing it? Resend code
                    </LemonButton>
                ) : (
                    <LemonButton
                        size="small"
                        center
                        onClick={() => {
                            closeModal()
                            openSupportForm({ kind: 'support' })
                        }}
                        data-attr="email-change-verification-contact-support"
                    >
                        Still not seeing it? Contact support
                    </LemonButton>
                )}
            </form>
        </LemonModal>
    )
}
