import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'

import { OrganizationMemberType } from '~/types'

import { askAdminToUpgradeLogic } from './askAdminToUpgradeLogic'

const MAX_ADMINS_LISTED = 3

/**
 * The path forward for a viewer who cannot open billing: name the organization admins who can
 * upgrade, instead of a call to action that lands them on the restricted billing page.
 */
export function AskAdminToUpgrade(): JSX.Element | null {
    const { admins, adminsLoading } = useValues(askAdminToUpgradeLogic)

    if (adminsLoading) {
        return null
    }

    return (
        <LemonBanner type="info" className="w-full mb-4 text-left">
            <span>
                Only organization admins can change the plan.{' '}
                {admins?.results.length ? (
                    <span>
                        Ask <AdminList admins={admins.results} total={admins.count} /> to upgrade.
                    </span>
                ) : (
                    <span>Ask an admin in your organization to upgrade.</span>
                )}
            </span>
        </LemonBanner>
    )
}

function AdminList({ admins, total }: { admins: OrganizationMemberType[]; total: number }): JSX.Element {
    const listed = admins.slice(0, MAX_ADMINS_LISTED)
    const remaining = total - listed.length

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
