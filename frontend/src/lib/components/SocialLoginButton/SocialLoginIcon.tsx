import { IconGithub } from '@posthog/icons'

import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { IconGitlab, IconGoogle, IconKey } from 'lib/lemon-ui/icons'

import { SSOProvider } from '~/types'

// IconGithub comes from the general icon set, which insets every glyph by 2 units inside a 24
// viewBox. IconGoogle and IconGitlab are brand marks drawn to the edge, so in a shared 28px box
// the GitHub mark rendered about 5px shorter. Cropping the inset lets all three fill the box.
const GITHUB_VIEW_BOX = '2 2 20 20'

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
        return <IconGithub {...props} viewBox={GITHUB_VIEW_BOX} />
    } else if (provider === 'gitlab') {
        return <IconGitlab {...props} />
    } else if (provider === 'chatgpt') {
        // The ChatGPT logo is the OpenAI mark. The Lemon icons size from the font size, so the mark does too.
        return <BrandMark name="OpenAI" className={props.className ?? 'size-[1em]'} />
    } else if (provider === 'saml' || provider === 'oidc') {
        return <IconKey {...props} />
    }
    return null
}
