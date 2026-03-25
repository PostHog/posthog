import { LemonDivider } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export type ValidatedPasswordResult = {
    score: number // 0 is no passsword - otherwise 1-5,
    feedback?: string
}

let zxcvbnFn: ((password: string) => { score: number; feedback: { suggestions: string[] } }) | null = null
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

    if (password.length > 72) {
        return {
            score: 0,
            feedback: 'Maximum 72 characters',
        }
    }

    if (!zxcvbnFn) {
        // Return basic length-based validation while zxcvbn is loading
        if (!password) {
            return { score: 0 }
        }
        if (password.length < 8) {
            return { score: 2, feedback: 'Must be at least 8 characters long' }
        }
        return { score: 3, feedback: '' }
    }

    const result = zxcvbnFn(password)

    if (result.score > 3 && password.length < 8) {
        return {
            score: 3,
            feedback: 'Must be at least 8 characters long',
        }
    }

    return {
        score: password ? result.score + 1 : 0,
        feedback: result.feedback.suggestions.join(' '),
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
