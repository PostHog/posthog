import type { ZXCVBNResult } from 'zxcvbn'

import { LemonDivider } from '@posthog/lemon-ui'

import { QuillPasswordStrength } from 'lib/components/QuillPasswordStrength'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

export type ValidatedPasswordResult = {
    score: number // 0 is no passsword - otherwise 1-5,
    feedback?: string
    crackTimeSeconds?: number
    crackTimeDisplay?: string | number
}

let zxcvbnFn: ((password: string) => ZXCVBNResult) | null = null
let zxcvbnLoading: Promise<boolean> | null = null

const PASSWORD_NEXT_STEP = "Try a longer password that isn't a common word or pattern."

// zxcvbn's suggestions assume passphrases ("Add another word or two"), so only its warning is
// shown, which names the weakness it found
function weakPasswordFeedback(warning: string): string {
    return warning ? `${warning}. ${PASSWORD_NEXT_STEP}` : `This password is too easy to guess. ${PASSWORD_NEXT_STEP}`
}

// We load zxcvbn asynchronously as it's a large dependency and we don't want to block the main thread
export function loadPasswordEstimator(): Promise<boolean> {
    if (zxcvbnFn) {
        return Promise.resolve(true)
    }
    if (!zxcvbnLoading) {
        zxcvbnLoading = import('zxcvbn')
            .then(({ default: zxcvbn }) => {
                zxcvbnFn = zxcvbn
                return true
            })
            .catch(() => {
                zxcvbnLoading = null
                return false
            })
    }
    return zxcvbnLoading
}

export function validatePassword(password: string = ''): ValidatedPasswordResult {
    void loadPasswordEstimator()

    if (password.length > 72) {
        return {
            score: 0,
            feedback: 'Maximum 72 characters',
        }
    }

    if (password.length > 0 && password.length < 8) {
        return {
            score: 2,
            feedback: 'Must be at least 8 characters long',
        }
    }

    if (!password) {
        return { score: 0 }
    }

    if (!zxcvbnFn) {
        // Return basic length-based validation while zxcvbn is loading
        return { score: 3, feedback: '' }
    }

    const result = zxcvbnFn(password)

    return {
        score: result.score + 1,
        feedback: result.score < 3 ? weakPasswordFeedback(result.feedback.warning) : '',
        crackTimeSeconds: result.guesses / 1e10,
        crackTimeDisplay: result.crack_times_display.offline_fast_hashing_1e10_per_second,
    }
}

export default function PasswordStrength({
    validatedPassword,
}: {
    validatedPassword: ValidatedPasswordResult
}): JSX.Element {
    const { score, feedback } = validatedPassword
    const quillSurface = useQuillSurface()

    if (quillSurface) {
        return <QuillPasswordStrength score={score} feedback={feedback} />
    }

    return (
        <Tooltip
            title={
                <>
                    Your password scores a{' '}
                    <strong className="flex gap-x-0.5">
                        <span>{score}</span>
                        <span>/</span>
                        <span>5</span>
                    </strong>
                    {feedback ? (
                        <>
                            <LemonDivider />
                            {feedback}
                        </>
                    ) : (
                        <> 💪 Nice!</>
                    )}
                </>
            }
        >
            <span className="w-20">
                <LemonProgress
                    percent={score * 20}
                    strokeColor={score <= 2 ? 'var(--danger)' : score <= 3 ? 'var(--warning)' : 'var(--success)'}
                />
            </span>
        </Tooltip>
    )
}
