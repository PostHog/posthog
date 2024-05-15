import { afterMount, connect, kea, path, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ReferralIdentity } from '~/types'

import type { myReferralsLogicType } from './MyReferralsType'

const myReferralsLogic = kea<myReferralsLogicType>([
    path(['scenes', 'settings', 'user', 'myReferralsLogic']),
    connect({
        values: [userLogic, ['user'], teamLogic, ['currentTeam']],
    }),
    loaders(({ values }) => ({
        referrerInfo: [
            null as ReferralIdentity | null,
            {
                loadReferrerInfo: async () => {
                    // We hardcode the values here as they are global
                    // TODO: Limit to cloud?

                    const host = window.location.origin // TODO: Update to us.posthog.com when ready
                    const referralProgram = '6ZrDckau' // TODO: Update to deployed value when ready
                    const token = values.currentTeam!.api_token // TODO: Update to 'sTMFPsFhdP1Ssg'

                    const response = await fetch(
                        host +
                            `/api/referrals/${referralProgram}/referrer/?token=${token}&referrer_id=${
                                values.user!.uuid
                            }`
                    )

                    if (response.status !== 200) {
                        throw new Error('Failed to load referrer info')
                    }
                    return response.json()
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadReferrerInfo()
    }),
])

export function MyReferrals(): JSX.Element {
    const { referrerInfo, referrerInfoLoading } = useValues(myReferralsLogic)

    return (
        <div className="text-center border-2 border-dashed rounded p-2">
            <h1 className="font-bold">Join our pyramid scheme</h1>
            <p>
                Want free stuff? Of course you do. Join our <b>totally original and unique</b> referral scheme to get
                sweet merch, platform credits, and good vibes. One referral = 1 vibe. Plus, get the tools to build your
                own ludicrously successful pyramid scheme included for free.
            </p>

            <CodeSnippet thing="referral link">
                {referrerInfoLoading
                    ? 'Mining bitcoins, please wait...'
                    : referrerInfo?.code
                    ? `${window.location.origin}/?rcode=${referrerInfo?.code}`
                    : 'Something went wrong...'}
            </CodeSnippet>
        </div>
    )
}
