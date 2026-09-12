import { combineUrl } from 'kea-router'
import { useCallback, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { SharedPageViewer } from '~/exporter/types'

import { SharedPageAccountMenu } from './SharedPageAccountMenu'
import { SharedPageShareButton } from './SharedPageShareButton'
import { useCloseOnWindowBlur } from './useCloseOnWindowBlur'

type OpenMenu = 'share' | 'account' | null

/** The right side of a shared page's top bar: the viewer's account, share the link, or a way to sign in. */
export function SharedPageActions({
    noun,
    viewer,
}: {
    noun: 'canvas' | 'file'
    /** Missing means the page was served without viewer hints, which reads the same as signed out. */
    viewer?: SharedPageViewer
}): JSX.Element {
    // One slot for both menus, so opening one closes the other.
    const [openMenu, setOpenMenu] = useState<OpenMenu>(null)
    useCloseOnWindowBlur(
        openMenu !== null,
        useCallback(() => setOpenMenu(null), [])
    )
    const menuProps = (menu: Exclude<OpenMenu, null>): { open: boolean; onOpenChange: (open: boolean) => void } => ({
        open: openMenu === menu,
        onOpenChange: (open) => setOpenMenu(open ? menu : openMenu === menu ? null : openMenu),
    })
    // The sharing page is not a routed scene, so every link here is a full navigation. `next` carries
    // this page's access token into the app, where lib/utils/shareTokenRedaction keeps it out of
    // captured events and replay.
    const signInUrl = combineUrl(urls.login(), { next: `${window.location.pathname}${window.location.search}` }).url

    return (
        <>
            {viewer?.is_authenticated && <SharedPageAccountMenu viewer={viewer} {...menuProps('account')} />}
            <SharedPageShareButton
                noun={noun}
                sharingEnabled={viewer?.sharing_enabled ?? true}
                sharingApiPath={viewer?.sharing_api_path}
                {...menuProps('share')}
            />
            {!viewer?.is_authenticated && (
                <LemonButton
                    type="secondary"
                    size="small"
                    to={signInUrl}
                    disableClientSideRouting
                    data-attr="shared-page-sign-in"
                >
                    Sign in
                </LemonButton>
            )}
        </>
    )
}
