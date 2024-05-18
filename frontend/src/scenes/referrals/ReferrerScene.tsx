import { LemonButton, LemonSkeleton, LemonTable, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet } from 'lib/components/CodeSnippet/CodeSnippet'
import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ReferralIdentity } from '~/types'

import { referrerLogic } from './referrerLogic'

export const scene: SceneExport = {
    component: ReferrerScene,
    logic: referrerLogic,
    paramsToProps: ({ params: { programId, userId } }): (typeof referrerLogic)['props'] => ({
        program_short_id: programId,
        id: userId && userId !== 'new' ? userId : 'new',
    }),
}

export function ReferrerScene(): JSX.Element {
    const { referrer, referralProgram, referrerLoading, referrerMissing } = useValues(referrerLogic)

    if (referrerMissing) {
        return <NotFound object="referral program" />
    }

    if (referrerLoading) {
        return <LemonSkeleton active />
    }

    return (
        <>
            <div className="flex flex-col gap-y-4">
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex-1 min-w-[20rem]">
                        <div className="mb-2">
                            <b>Program</b>
                            <div className="w-fit min-w-40 mt-2">
                                <Link to={urls.referralProgram(referralProgram.short_id)}>{referralProgram.title}</Link>
                            </div>
                        </div>
                    </div>
                </div>
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex-1 min-w-[20rem]">
                        <div className="mb-2">
                            <b>Referral code</b>
                            <div className="w-fit min-w-40 mt-2">
                                <CodeSnippet>{referrer.code}</CodeSnippet>
                            </div>
                        </div>
                    </div>
                </div>
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex-1 min-w-[20rem]">
                        <div className="mb-2">
                            <b>Referrer ID</b>
                            <div className="w-fit min-w-40 mt-2">
                                <CodeSnippet>{referrer.user_id}</CodeSnippet>
                            </div>
                        </div>
                    </div>
                </div>
                <div className="flex gap-x-24">
                    <p>
                        <span className="font-bold text-lg">{referrer.total_redemptions} redeemers</span>
                        {referrer.max_redemption_count && (
                            <>
                                <span className="text-muted">/{referrer.max_redemption_count} allowed</span>
                            </>
                        )}
                    </p>
                    <p>
                        <span className="font-bold text-lg">{referrer.total_points || 0}</span>{' '}
                        <span className="text-muted">points</span>
                    </p>
                </div>
            </div>
            <RedeemersTable referrer={referrer} />
        </>
    )
}

const RedeemersTable = ({ referrer }: { referrer: ReferralIdentity }): JSX.Element => {
    return (
        <div>
            <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold">Redeemers</h2>
                <LemonButton type="primary">Add redeemer</LemonButton>
            </div>
            <LemonTable
                columns={[
                    {
                        key: 'user_id',
                        dataIndex: 'user_id',
                        title: 'Redeemer',
                        render: (_, state) => state.email ?? state.user_id,
                    },
                    {
                        key: 'created_at',
                        dataIndex: 'created_at',
                        title: 'Created at',
                    },
                    {
                        key: 'points',
                        dataIndex: 'points',
                        title: 'Points',
                        render: (points) => <span>{points || 0}</span>,
                    },
                ]}
                dataSource={referrer.redeemers}
                emptyState="No redeemers for this program and referrer yet. Create one!"
            />
        </div>
    )
}
