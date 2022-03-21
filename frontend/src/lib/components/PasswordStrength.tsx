import React from 'react'
import { Progress } from 'antd'
import zxcvbn from 'zxcvbn'

export default function PasswordStrength({ password = '' }: { password: string }): JSX.Element {
    // passwordScore is 0 if no password input
    // passwordScore is 20, 40, 60, 80, or 100 if password input, based on zxcvbn score (which is 0, 1, 2, 3, or 4)
    const passwordScore: number = password.length && zxcvbn(password).score * 20 + 20

    return (
        <Progress
            percent={passwordScore}
            size="small"
            strokeColor={
                passwordScore <= 50 ? 'var(--danger)' : passwordScore <= 75 ? 'var(--warning)' : 'var(--success)'
            }
            showInfo={false}
        />
    )
}
