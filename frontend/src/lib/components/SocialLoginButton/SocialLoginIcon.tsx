import { IconGithub } from '@posthog/icons'
import { IconGitlab, IconGoogle, IconKey } from 'lib/lemon-ui/icons'

import { SSOProvider } from '~/types'

export const SocialLoginIcon = (provider: SSOProvider): JSX.Element | undefined => {
    if (provider === 'google-oauth2') {
        return <IconGoogle />
    } else if (provider === 'github') {
        return <IconGithub />
    } else if (provider === 'gitlab') {
        return <IconGitlab />
    } else if (provider === 'saml') {
        return <IconKey />
    }
}
