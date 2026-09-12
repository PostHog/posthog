import { LemonDivider } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export type ValidatedPasswordResult = {
    score: number // 0 is no password - otherwise 1-5
    feedback?: string // set only when the password is rejected, so call sites can use it as the field error
}

// zxcvbn's own suggestions are library copy, so we map its score onto ours instead.
// A zxcvbn score of 3 or more is accepted, which matches ZxcvbnValidator on the backend.
const TOO_EASY_TO_GUESS = 'This password is too easy to guess. Make it longer, or use a few unrelated words.'
const WEAK_PASSWORD_FEEDBACK: Record<number, string> = {
    0: TOO_EASY_TO_GUESS,
    1: TOO_EASY_TO_GUESS,
    2: 'This password is still easy to guess. Add more words or characters.',
}

let zxcvbnFn: ((password: string) => { score: number }) | null = null
let zxcvbnLoading = false

// We load zxcvbn asynchronously as it's a large dependency and we don't want to block the main thread
function ensureZxcvbnLoaded(): void {
    if (!zxcvbnFn && !zxcvbnLoading) {
        zxcvbnLoading = true
        void import('zxcvbn')
            .then(({ default: zxcvbn }) => {
                zxcvbnFn = zxcvbn
            })
            .catch(() => {
                zxcvbnLoading = false
            })
    }
}

export function validatePassword(password: string = ''): ValidatedPasswordResult {
    ensureZxcvbnLoaded()

    if (!password) {
        return { score: 0 }
    }

    if (password.length > 72) {
        return {
            score: 0,
            feedback: 'Maximum 72 characters',
        }
    }

    if (password.length < 8) {
        return {
            score: 2,
            feedback: 'Must be at least 8 characters long',
        }
    }

    if (!zxcvbnFn) {
        // Return basic length-based validation while zxcvbn is loading
        return { score: 3 }
    }

    const { score } = zxcvbnFn(password)

    return {
        score: score + 1,
        feedback: WEAK_PASSWORD_FEEDBACK[score],
    }
}

export default function PasswordStrength({
    validatedPassword,
}: {
    validatedPassword: ValidatedPasswordResult
}): JSX.Element {
    const { score, feedback } = validatedPassword

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
