import { useActions, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { Button, Dialog, DialogContent, DialogDescription, DialogTitle, Text } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { isValidVerificationCode } from 'scenes/authentication/shared/verificationCode'
import { VerificationCodeInput } from 'scenes/authentication/shared/VerificationCodeInput'
import { userLogic } from 'scenes/userLogic'

import { MAX_RESENDS, emailChangeVerificationLogic } from './emailChangeVerificationLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function QuillEmailChangeVerificationModal({
    onSubmit,
    onContactSupport,
}: {
    onSubmit: () => void
    onContactSupport: () => void
}): JSX.Element {
    const {
        modalOpen,
        verificationCode,
        verificationCodeError,
        verificationResultLoading,
        resendResultLoading,
        resendCooldown,
        resendsUsed,
    } = useValues(emailChangeVerificationLogic)
    const { closeModal, setVerificationCode, resendCode } = useActions(emailChangeVerificationLogic)
    const { user } = useValues(userLogic)

    return (
        <Dialog open={modalOpen} onOpenChange={(nextOpen: boolean) => !nextOpen && closeModal()}>
            <DialogContent>
                <form
                    className="flex flex-col items-center gap-2 p-2 text-center"
                    // The code input renders a hidden input with a \d{6} pattern. Without noValidate,
                    // the browser blocks an Enter-key submit on a partial code and shows no feedback.
                    noValidate
                    onSubmit={(e) => {
                        e.preventDefault()
                        onSubmit()
                    }}
                >
                    <HedgehogMagnifyingGlass className="block w-auto mx-auto h-28" />
                    <DialogTitle className="m-0">Check your inbox</DialogTitle>
                    <DialogDescription className="m-0 text-pretty">
                        We emailed a 6-digit code to <strong>{user?.pending_email}</strong>. Enter it below to verify
                        your new address. The code is valid for 30 minutes.
                    </DialogDescription>
                    <VerificationCodeInput
                        value={verificationCode}
                        onChange={setVerificationCode}
                        onComplete={onSubmit}
                        disabled={verificationResultLoading}
                        data-attr="email-change-verification-code"
                        status={verificationCodeError ? 'danger' : 'default'}
                    />
                    {verificationCodeError && (
                        <Text size="xs" variant="destructive" role="alert" render={<p className="m-0" />}>
                            {verificationCodeError}
                        </Text>
                    )}
                    <Button
                        variant="primary"
                        size="lg"
                        className="w-full"
                        type="submit"
                        loading={verificationResultLoading}
                        disabledReason={
                            isValidVerificationCode(verificationCode)
                                ? undefined
                                : 'Enter the 6-digit code from your email'
                        }
                        data-attr="email-change-verification-submit"
                    >
                        Verify email
                    </Button>
                    {resendsUsed < MAX_RESENDS ? (
                        <Button
                            loading={resendResultLoading}
                            disabledReason={resendCooldown > 0 ? `You can resend in ${resendCooldown}s` : undefined}
                            onClick={resendCode}
                            data-attr="email-change-verification-resend"
                        >
                            Resend code
                        </Button>
                    ) : (
                        <Button onClick={onContactSupport} data-attr="email-change-verification-contact-support">
                            Still not seeing it? Contact support
                        </Button>
                    )}
                </form>
            </DialogContent>
        </Dialog>
    )
}
