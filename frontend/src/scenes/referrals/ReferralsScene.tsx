import { useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTable, LemonTableColumns, Spinner, Tooltip } from '@posthog/lemon-ui'

import { WavingHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SocialReferralListItem, referralsSceneLogic } from './referralsSceneLogic'

function ReferralsAttributedSignupsIntro({
    referralShareUrl,
    copyDisabledReason,
}: {
    referralShareUrl: string | null
    copyDisabledReason: string | undefined
}): JSX.Element {
    return (
        <div
            data-attr="referrals-attributed-signups-empty"
            className="flex flex-col-reverse sm:flex-row items-center justify-center gap-6 w-full max-w-[40rem] mx-auto"
        >
            <div className="flex flex-col gap-3 flex-1 min-w-0 text-center sm:text-left">
                <p className="m-0 text-[17px] font-semibold text-default leading-snug text-balance">
                    Your fan club spreadsheet is peacefully empty
                </p>
                <p className="m-0 text-secondary text-[15px] leading-relaxed text-balance">
                    The moment someone waltzes into PostHog through your link, they&apos;ll flop into this tidy little
                    list with timestamps and onboarding progress sprinkled in for context. Until then—air out your link
                    somewhere fun and check back like someone peeking into a warmed-up oven.
                </p>
                <div className="flex flex-wrap gap-2 justify-center sm:justify-start pt-0.5">
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconCopy />}
                        disabledReason={copyDisabledReason}
                        data-attr="referrals-empty-copy-link"
                        onClick={() => {
                            if (referralShareUrl) {
                                void copyToClipboard(referralShareUrl, 'referral link')
                            }
                        }}
                    >
                        Copy signup link
                    </LemonButton>
                </div>
            </div>
            <div className="shrink-0" aria-hidden>
                <WavingHog alt="" draggable={false} className="w-32 sm:w-[8.75rem] h-auto drop-shadow-md" />
            </div>
        </div>
    )
}

export function ReferralsScene(): JSX.Element {
    const { referrals, referralsLoading, referralShareUrl } = useValues(referralsSceneLogic)

    const columns: LemonTableColumns<SocialReferralListItem> = [
        {
            title: 'ID',
            dataIndex: 'id',
            width: 280,
            render: (_, row) => (
                <code className="text-xs whitespace-nowrap overflow-hidden text-ellipsis block max-w-[260px]">
                    {row.id}
                </code>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (_, row) => (row.created_at ? dayjs(row.created_at).format('LLL') : '–'),
            sorter: (a, b) => dayjs(a.created_at).unix() - dayjs(b.created_at).unix(),
        },
        {
            title: 'Tracked orgs',
            key: 'tracked',
            render: (_, row) => String(Object.keys(row.referee_state || {}).length),
        },
        {
            title: 'State',
            key: 'referee_state',
            render: (_, row) => (
                <pre className="text-xs font-mono whitespace-pre-wrap break-all max-w-xl max-h-32 overflow-auto m-0 bg-surface-primary p-2 rounded">
                    {JSON.stringify(row.referee_state ?? {}, null, 2)}
                </pre>
            ),
        },
    ]

    const copyDisabledReason = !referralShareUrl ? 'Loading user…' : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Referrals].name}
                description={sceneConfigurations[Scene.Referrals].description}
                resourceType={{ type: 'link' }}
            />

            <LemonCard hoverEffect={false} className="mb-10 overflow-hidden shadow-sm border-primary p-0">
                <div className="relative">
                    <div
                        aria-hidden
                        className="absolute inset-y-0 left-0 w-1 rounded-l bg-gradient-to-b from-accent-active to-accent"
                    />
                    <div className="pl-6 pr-6 py-6 flex flex-col gap-5">
                        <div className="flex gap-4 min-w-0">
                            <div className="hidden sm:flex shrink-0 size-11 rounded-xl items-center justify-center bg-accent-highlight-secondary border border-accent/25">
                                <IconCopy className="text-accent text-xl" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <p className="m-0 text-lg font-semibold text-default tracking-tight">
                                    Your signup link
                                </p>
                                <p className="m-0 mt-1 text-secondary text-[15px] leading-snug max-w-2xl">
                                    Drop this wherever you yak about analytics—your team chat, timeline, sleepy
                                    newsletter footer, whichever. Anyone who swings by and joins shows up below as yours
                                    ✨
                                </p>
                            </div>
                        </div>

                        {!referralShareUrl ? (
                            <div className="flex items-center gap-2 text-secondary text-sm">
                                <Spinner />
                                Preparing your link…
                            </div>
                        ) : (
                            <div className="flex flex-col sm:flex-row gap-3 sm:items-stretch">
                                <Tooltip title={<span className="font-normal break-all">{referralShareUrl}</span>}>
                                    <div
                                        data-attr="social-referral-link"
                                        className="flex-1 min-w-0 rounded-lg border border-primary bg-fill-secondary px-3.5 py-3 shadow-[inset_0_1px_0_rgba(0,0,0,0.04)] dark:shadow-none"
                                    >
                                        <span className="block font-mono text-[13px] text-default truncate select-all cursor-default">
                                            {referralShareUrl}
                                        </span>
                                    </div>
                                </Tooltip>
                                <LemonButton
                                    type="primary"
                                    size="medium"
                                    className="shrink-0"
                                    icon={<IconCopy />}
                                    disabledReason={copyDisabledReason}
                                    data-attr="social-referral-copy"
                                    onClick={() => {
                                        if (referralShareUrl) {
                                            void copyToClipboard(referralShareUrl, 'referral link')
                                        }
                                    }}
                                >
                                    Copy link
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
            </LemonCard>

            <header className="mb-4">
                <h2 className="m-0 text-[15px] font-semibold text-default">Attributed signups</h2>
                <p className="m-0 mt-1 text-secondary text-sm">Referrals tracked from your link appear in this list.</p>
            </header>
            {referralsLoading || (referrals?.length ?? 0) > 0 ? (
                <LemonTable columns={columns} dataSource={referrals ?? []} loading={!!referralsLoading} rowKey="id" />
            ) : (
                <LemonCard hoverEffect={false} className="shadow-sm border-primary">
                    <ReferralsAttributedSignupsIntro
                        referralShareUrl={referralShareUrl}
                        copyDisabledReason={copyDisabledReason}
                    />
                </LemonCard>
            )}
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: ReferralsScene,
    logic: referralsSceneLogic,
}
