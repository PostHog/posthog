import React, { useState, useEffect } from 'react'
import { Progress } from 'antd'

function PasswordStrength(props) {
    const { password } = props
    const [passwordProgressState, setPasswordProgressState] = useState(0)

    const MAX_PASSWORD_STRENGTH = 6

    const calculatePasswordStrength = (password) => {
        if (!password) return 0
        const rawValue =
            /.{8,}/.test(password) + // at least 8 characters
            /.{12,}/.test(password) + // bonus if longer than 12 chars
            /[a-z]/.test(password) + // at least one lowercase letter
            /[A-Z]/.test(password) + // at least one uppercase letter
            /\d/.test(password) + // at least one number
            /[^A-Za-z0-9]/.test(password) // at least one special character
        return (rawValue / MAX_PASSWORD_STRENGTH) * 100
    }

    useEffect(() => {
        setPasswordProgressState(calculatePasswordStrength(password))
    }, [password])

    return (
        <Progress
            percent={passwordProgressState}
            size="small"
            strokeColor={passwordProgressState < 50 ? '#e23d20' : passwordProgressState < 80 ? '#f5c115' : '#0fca16'}
            showInfo={false}
        />
    )
}

export default PasswordStrength
