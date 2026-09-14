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
        // 400px gives the same content width as the auth card, so the button does not dwarf the code boxes
        <LemonModal isOpen={modalOpen} onClose={closeModal} simple width={400}>
            <form
                className="flex flex-col items-center gap-2.5 p-6 text-center"
                // The code input renders a hidden input with a \d{6} pattern. Without noValidate,
                // the browser blocks an Enter-key submit on a partial code and shows no feedback.
                noValidate
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
                    We emailed a 6-digit code to <strong>{user?.pending_email}</strong>. Enter it below to verify your
                    new address. The code is valid for 30 minutes.
                </p>
                <VerificationCodeInput
                    value={verificationCode}
                    onChange={setVerificationCode}
                    onComplete={() => {
                        if (!verificationResultLoading) {
                            submitVerificationCode()
                        }
                    }}
                    disabled={verificationResultLoading}
                    data-attr="email-change-verification-code"
                    status={verificationCodeError ? 'danger' : 'default'}
                />
                {verificationCodeError && (
                    <p className="m-0 text-sm text-danger" role="alert">
                        {verificationCodeError}
                    </p>
                )}
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
                        Resend code
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
