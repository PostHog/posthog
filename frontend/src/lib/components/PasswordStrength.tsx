import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import zxcvbn from 'zxcvbn'

export default function PasswordStrength({
    password = '',
    className,
}: {
    password?: string
    className?: string
}): JSX.Element {
    // passwordScore is 0 if no password input
    // passwordScore is 20, 40, 60, 80, or 100 if password input, based on zxcvbn score (which is 0, 1, 2, 3, or 4)
    const passwordScore: number = password.length && zxcvbn(password).score * 20 + 20

    return (
        <Tooltip title="Password strength">
            <LemonProgress
                percent={passwordScore}
                strokeColor={
                    passwordScore <= 50 ? 'var(--danger)' : passwordScore <= 75 ? 'var(--warning)' : 'var(--success)'
                }
                className={className}
            />
        </Tooltip>
    )
}
