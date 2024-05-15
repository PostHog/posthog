import { LemonSkeleton, lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, useActions, useValues } from 'kea'
import { loaders } from 'kea-loaders'
import { getCookie, setCookie } from 'lib/api'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { useEffect } from 'react'
import { userLogic } from 'scenes/userLogic'

import { ReferralIdentity } from '~/types'

import type { myReferralsLogicType } from './MyReferralsType'

export const myReferralsLogic = kea<myReferralsLogicType>([
    path(['scenes', 'settings', 'user', 'myReferralsLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    actions({
        redeemReferralIfExists: true,
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
                    const token = 'phc_g5GJ0z1vcm2HOpatOT2484heTH66tpoS2cIyZy4khxb' // TODO: Update to 'sTMFPsFhdP1Ssg'
                    const email = values.user!.email

                    const response = await fetch(
                        host +
                            `/api/referrals/${referralProgram}/referrer/?token=${token}&user_id=${
                                values.user!.uuid
                            }&user_email=${email}`
                    )

                    if (response.status !== 200) {
                        throw new Error('Failed to load referrer info')
                    }
                    return response.json()
                },
            },
        ],
    })),
    listeners(({ values }) => ({
        redeemReferralIfExists: async () => {
            const code = getCookie('ph_rcode')
            // TODO: Remove testing code
            const userID = values.user?.uuid ?? Math.round(Math.random() * 10000)
            const email = values.user?.email ?? `${userID}-test@posthog.com`
            if (!code) {
                console.log('NO CODE OR NO USER')
                return
            }
            const host = window.location.origin // TODO: Update to us.posthog.com when ready
            const referralProgram = '6ZrDckau' // TODO: Update to deployed value when ready
            const token = 'phc_g5GJ0z1vcm2HOpatOT2484heTH66tpoS2cIyZy4khxb' // TODO: Update to 'sTMFPsFhdP1Ssg'

            const response = await fetch(
                host +
                    `/api/referrals/${referralProgram}/redeem/?token=${token}&code=${code}&user_id=${userID}&user_email=${email}`
            )

            if (response.status !== 200) {
                lemonToast.error('Failed to redeem code 💩')
                throw new Error('Failed to redeem!')
            }

            lemonToast.success('Code redeemed! 🎉')

            setCookie('ph_rcode', '', -1)

            return response.json()
        },
    })),

    afterMount(({ actions }) => {
        actions.redeemReferralIfExists()
    }),
])

export function MyReferrals(): JSX.Element {
    const { referrerInfo, referrerInfoLoading } = useValues(myReferralsLogic)
    const { loadReferrerInfo } = useActions(myReferralsLogic)

    const redeemed = referrerInfo?.total_redemptions ?? 0
    const fontSize = 1 + redeemed / 10

    useEffect(() => loadReferrerInfo(), [])

    return (
        <div className="text-center border-2 border-dashed rounded p-4">
            <h1 className="font-bold">Join our pyramid scheme</h1>
            <p>
                Want free stuff? Of course you do. Join our <b>totally original and unique</b> referral scheme to get
                sweet merch, platform credits, and good vibes. One referral = 1 vibe. Plus, get the tools to build your
                own ludicrously successful pyramid scheme included for free.
            </p>

            <p>
                Share the link with your friends. If they use your link and sign up for PostHog then free stuff comes
                your way!
            </p>

            <CodeSnippet thing="referral link">
                {referrerInfoLoading
                    ? 'Mining bitcoins, please wait...'
                    : referrerInfo?.code
                    ? `${window.location.origin}/#rcode=${referrerInfo?.code}`
                    : 'Something went wrong...'}
            </CodeSnippet>

            {referrerInfoLoading ? (
                <LemonSkeleton className="mt-4" />
            ) : (
                <>
                    <p className="italic text-muted-alt mt-4">
                        So far,{' '}
                        <b
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                fontSize: `${fontSize}rem`,
                            }}
                        >
                            {redeemed} people
                        </b>{' '}
                        have redeemed your code.
                    </p>

                    {redeemed === 0 ? (
                        <p className="text-muted-alt text-xs italic font-semibold opacity-50">
                            Not gonna lie - that's a bit embarrassing.
                        </p>
                    ) : redeemed < 5 ? (
                        <p className="text-muted-alt text-xs italic font-semibold opacity-75">
                            Amazing! Keep it up and you'll be rolling in free stuff in no time.
                        </p>
                    ) : redeemed < 10 ? (
                        <p className="text-muted-alt text-xs italic font-semibold opacity-75">
                            You are basically an influencer now. Quit your day job - you've found your calling.
                        </p>
                    ) : (
                        <p className="text-muted-alt text-xs italic font-semibold opacity-100">
                            Please stop referring us. Our servers are on fire and our support team is crying.
                        </p>
                    )}
                </>
            )}
        </div>
    )
}
