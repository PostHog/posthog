import { useActions } from 'kea'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { userLogic } from 'scenes/userLogic'

import { SharedPageViewer } from '~/exporter/types'

/** The signed-in viewer's avatar on a shared page: who they are, the way into PostHog, and sign out. */
export function SharedPageAccountMenu({
    viewer,
    open,
    onOpenChange,
}: {
    viewer: SharedPageViewer
    open: boolean
    onOpenChange: (open: boolean) => void
}): JSX.Element {
    const { logout } = useActions(userLogic)
    const user = { email: viewer.email ?? '', first_name: viewer.first_name ?? '' }

    return (
        <LemonMenu
            visible={open}
            onVisibilityChange={onOpenChange}
            placement="bottom-end"
            items={[
                {
                    title: (
                        <div className="flex flex-col gap-0.5 px-2 py-1 font-normal normal-case">
                            {viewer.first_name && (
                                <span className="font-semibold text-default">{viewer.first_name}</span>
                            )}
                            <span className="text-muted">{viewer.email}</span>
                        </div>
                    ),
                    items: [
                        {
                            label: 'Open PostHog',
                            to: '/',
                            disableClientSideRouting: true,
                            'data-attr': 'shared-page-open-app',
                        },
                        // Sign-out lands on the login page with this page as its way back.
                        { label: 'Sign out', onClick: () => logout(true), 'data-attr': 'shared-page-sign-out' },
                    ],
                },
            ]}
        >
            {/* The trigger is not the popover's DOM reference, so without the opt-out its pointerdown dismisses
                the menu and the click that follows reopens it. */}
            <LemonButton
                type="tertiary"
                size="small"
                icon={<ProfilePicture user={user} size="sm" />}
                className={CLICK_OUTSIDE_BLOCK_CLASS}
                aria-label="Account"
                data-attr="shared-page-account"
            />
        </LemonMenu>
    )
}
