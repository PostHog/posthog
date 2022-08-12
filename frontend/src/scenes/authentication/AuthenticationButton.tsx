import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import React from 'react'

export const AuthenticationButton = (props: LemonButtonProps): JSX.Element => {
    return <LemonButton fullWidth type="primary" status="primary-alt" center size="large" {...props} />
}
