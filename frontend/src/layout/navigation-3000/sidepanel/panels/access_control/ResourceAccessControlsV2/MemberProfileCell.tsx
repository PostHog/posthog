import { ProfilePicture } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'

export function MemberProfileCell({
    user,
}: {
    user: { uuid: string; first_name: string; email: string }
}): JSX.Element {
    return (
        <div className="flex items-center gap-3">
            <ProfilePicture user={user} />
            <div className="overflow-hidden">
                {user.first_name ? (
                    <>
                        <p className="font-medium mb-0 truncate">{fullName(user)}</p>
                        <p className="text-secondary font-light mb-0 truncate text-xs">{user.email}</p>
                    </>
                ) : (
                    <p className="text-secondary mb-0 truncate">{user.email}</p>
                )}
            </div>
        </div>
    )
}
