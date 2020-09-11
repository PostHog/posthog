import React from 'react'
import { Progress } from 'antd'
import { green, orange, red } from '@ant-design/colors'

const PASSWORD_TEST_REGEXES: RegExp[] = [
    /.{8,}/, // at least 8 characters
    /.{12,}/, // bonus if longer than 12 characters
    /[a-z]/, // at least one lowercase letter
    /[A-Z]/, // at least one uppercase letter
    /\d/, // at least one number
    /[^A-Za-z0-9]/, // at least one special character
]

function scorePassword(password?: string): number {
    if (!password) return 0
    const testsPassed: number = PASSWORD_TEST_REGEXES.reduce(
        (accumulator: number, regex: RegExp) => accumulator + Number(regex.test(password)),
        0
    )
    return (testsPassed / PASSWORD_TEST_REGEXES.length) * 100
}

export default function PasswordStrength({ password }: { password: string }): JSX.Element {
    const passwordScore: number = scorePassword(password)

    return (
        <Progress
            percent={passwordScore}
            size="small"
            strokeColor={passwordScore < 50 ? red.primary : passwordScore < 80 ? orange.primary : green.primary}
            showInfo={false}
        />
    )
}
