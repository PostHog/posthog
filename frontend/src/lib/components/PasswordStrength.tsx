import { LemonDivider } from '@posthog/lemon-ui'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import zxcvbn from 'zxcvbn'

export type ValidatedPasswordResult = {
    score: number // 0 is no passsword - otherwise 1-5,
    feedback?: string
}

export function validatePassword(password: string = ''): ValidatedPasswordResult {
    // Checks the validation against the zxcvbn library
    // and any other custom validation we have

    const result = zxcvbn(password)

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
                    <strong className="space-x-0.5">
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
