import React from 'react'
import { Progress } from 'antd'
import { green, orange, red, yellow } from '@ant-design/colors'
import zxcvbn from 'zxcvbn'

export default function PasswordStrength({ password = '' }: { password: string }): JSX.Element {
    const MAX_ZXCVBN_SCORE = 4
    const passwordScore: number = (zxcvbn(password).score / MAX_ZXCVBN_SCORE) * 100

    return (
        <Progress
            percent={passwordScore === 0 && password.length > 0 ? 10 : passwordScore}
            size="small"
            strokeColor={
                passwordScore < 25
                    ? red.primary
                    : passwordScore < 50
                    ? orange.primary
                    : passwordScore < 75
                    ? yellow.primary
                    : green.primary
            }
            showInfo={false}
        />
    )
}
