import { Text } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullNameOrEmail } from 'lib/utils/strings'

import { QuillMemberRolesPicker } from './QuillMemberRolesPicker'
import type { AccessControlMemberEntry } from './types'

export function QuillMemberAccessHeader({ member }: { member: AccessControlMemberEntry }): JSX.Element {
    const name = fullNameOrEmail(member.user)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex min-w-0 items-center gap-3">
                <QuillPersonAvatar name={name} email={member.user.email} size="default" />
                <div className="flex min-w-0 flex-col">
                    <Text size="sm" weight="medium" render={<span className="truncate ph-no-capture" />}>
                        {name}
                    </Text>
                    {member.user.first_name && (
                        <Text size="xs" variant="muted" render={<span className="truncate ph-no-capture" />}>
                            {member.user.email}
                        </Text>
                    )}
                </div>
            </div>
            <QuillMemberRolesPicker userUuid={member.user.uuid} />
        </div>
    )
}
