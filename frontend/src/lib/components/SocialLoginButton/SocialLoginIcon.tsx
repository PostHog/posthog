import { IconGitLab, IconGithub } from '@posthog/icons'

import { IconGoogle, IconKey } from 'lib/lemon-ui/icons'

import { SSOProvider } from '~/types'

export const SocialLoginIcon = ({
    provider,
    ...props
}: {
    provider: SSOProvider
    className?: string
}): JSX.Element | null => {
    if (provider === 'google-oauth2') {
        return <IconGoogle {...props} />
    } else if (provider === 'github') {
        return <IconGithub {...props} />
    } else if (provider === 'gitlab') {
        return <IconGitLab {...props} />
    } else if (provider === 'saml') {
        return <IconKey {...props} />
    }
    return null
}
