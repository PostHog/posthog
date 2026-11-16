import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { useInterval } from 'lib/hooks/useInterval'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { loginLogic } from '../loginLogic'

const LINK_CLASS_NAME =
    'font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary'

function formatCountdown(totalSeconds: number): string {
    const minutes = Math.floor(totalSeconds / 60)
    const seconds = totalSeconds % 60
    return `${minutes}:${String(seconds).padStart(2, '0')}`
}

export function LoginCodeResend(): JSX.Element {
    const { resendCodeBasedVerification } = useActions(loginLogic)
    const { codeResendAvailableAt, resendResponseLoading, resendResponse, codeResendAttempted, codeVerificationEmail } =
        useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { sendSupportRequest } = useValues(supportLogic)

    const [now, setNow] = useState(() => Date.now())
    // The interval stops at zero, so a resend must refresh `now` or the restarted countdown starts from a stale time
    useEffect(() => setNow(Date.now()), [codeResendAvailableAt])
    const secondsLeft =
        codeResendAvailableAt === null ? 0 : Math.max(0, Math.ceil((codeResendAvailableAt - now) / 1000))
    useInterval(() => setNow(Date.now()), secondsLeft > 0 ? 1000 : null)

    return (
        <div className="flex flex-col items-center gap-1 text-sm text-secondary text-center">
            {secondsLeft > 0 ? (
                <p className="m-0">
                    {resendResponse?.success ? 'Code sent. ' : ''}You can send a new code in{' '}
                    <span className="tabular-nums">{formatCountdown(secondsLeft)}</span>
                </p>
            ) : (
                <p className="m-0">
                    Didn't get the code?{' '}
                    <Link
                        onClick={() => resendCodeBasedVerification(null)}
                        disabledReason={resendResponseLoading ? 'Sending...' : undefined}
                        className={LINK_CLASS_NAME}
                        data-attr="login-code-resend"
                    >
                        Resend code
                    </Link>
                </p>
            )}
            {codeResendAttempted && preflight?.cloud && (
                <p className="text-xs mb-0">
                    <span>Still nothing? </span>
                    <Link
                        data-attr="login-code-contact-support"
                        onClick={(e) => {
                            e.preventDefault()
                            openSupportForm({
                                kind: 'support',
                                email: codeVerificationEmail ?? undefined,
                                message: sendSupportRequest.message
                                    ? undefined
                                    : `I need help logging in.\nI haven't received the emailed verification code.${
                                          preflight?.region ? `\nData region: ${preflight.region}` : ''
                                      }`,
                            })
                        }}
                        className={LINK_CLASS_NAME}
                    >
                        Contact support
                    </Link>
                </p>
            )}
        </div>
    )
}
