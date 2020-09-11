import React from 'react'
import { Progress } from 'antd'
import { green, orange, red, yellow } from '@ant-design/colors'

function scorePassword(password?: string): number {
    if (!password) return 0

    let score: number = 0
    const passwordLength = password.length

    for (let i = 0; i < Math.min(passwordLength, 21); ++i) {
        const char = password[i]
        if (/[a-z]/.test(char)) score += 1
        // 1 point for lowercase characters
        else if (/[A-Z]/.test(char)) score += 2
        // 2 points for uppercase characters
        else if (/\d/.test(char)) score += 3
        // 3 points for number
        else if (/[^A-Za-z0-9]/.test(char)) score += 4 // 4 points for special characters
    }

    // 2 points for being longer than 12
    if (passwordLength >= 12) score += 2

    // Password strength can only improve after 20 characters
    const lengthBonusPoints = passwordLength >= 20 ? (passwordLength - 20) * 2 : 0
    score += lengthBonusPoints

    // Penalty for character repetition and short length
    const distinctChars = new Set(password)
    if (distinctChars.size * 3 < passwordLength || passwordLength <= 8) score /= 2

    // topScore = All symbols up to 20 characters + 2 points for length > 12 + Bonus points for length over 20
    const topScore = Math.min(passwordLength, 20) * 4 + 2 + lengthBonusPoints
    return (score / topScore) * 100
}

export default function PasswordStrength({ password }: { password: string }): JSX.Element {
    const passwordScore: number = scorePassword(password)

    return (
        <Progress
            percent={passwordScore}
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
