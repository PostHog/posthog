import { GithubIcon, GitlabIcon, GoogleIcon, IconKey } from 'lib/lemon-ui/icons'

import { SSOProvider } from '~/types'

export const SocialLoginIcon = (provider: SSOProvider): JSX.Element | undefined => {
    if (provider === 'google-oauth2') {
        return <GoogleIcon />
    } else if (provider === 'github') {
        return <GithubIcon />
    } else if (provider === 'gitlab') {
        return <GitlabIcon />
    } else if (provider === 'saml') {
        return <IconKey />
    }
}
