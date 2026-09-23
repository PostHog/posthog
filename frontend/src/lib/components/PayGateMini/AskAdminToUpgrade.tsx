import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { OrganizationMemberType } from '~/types'

const MAX_ADMINS_LISTED = 3

/**
 * The path forward for a viewer who cannot open billing: name the organization admins who can
 * upgrade, instead of a call to action that lands them on the restricted billing page.
 */
export function AskAdminToUpgrade(): JSX.Element {
    const { sortedMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useEffect(() => {
        ensureAllMembersLoaded()
    }, [ensureAllMembersLoaded])

    const admins = sortedMembers?.filter((member) => member.level >= OrganizationMembershipLevel.Admin)

    return (
        <LemonBanner type="info" className="w-full mb-4 text-left">
            <span>
                Only organization admins can change the plan.{' '}
                {admins?.length ? (
                    <span>
                        Ask <AdminList admins={admins} /> to upgrade.
                    </span>
                ) : membersLoading ? null : (
                    <span>Ask an admin in your organization to upgrade.</span>
                )}
            </span>
        </LemonBanner>
    )
}

function AdminList({ admins }: { admins: OrganizationMemberType[] }): JSX.Element {
    const listed = admins.slice(0, MAX_ADMINS_LISTED)
    const remaining = admins.length - listed.length

    return (
        <>
            {listed.map((admin, index) => (
                <span key={admin.user.uuid}>
                    {index > 0 && (index === listed.length - 1 && !remaining ? ' or ' : ', ')}
                    <Link to={`mailto:${admin.user.email}`}>{fullName(admin.user) || admin.user.email}</Link>
                </span>
            ))}
            {remaining > 0 && <span> or {remaining} more</span>}
        </>
    )
}
