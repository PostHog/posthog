import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { urls } from '../urls'

const endDate = dayjs.tz('2025-11-06T00:00:00Z', 'UTC')
const startDate = dayjs.tz('2025-10-29T12:00:00Z', 'UTC')

function pad(n: number): string {
    return n.toString().padStart(2, '0')
}

export default function FireSaleBanner(): JSX.Element {
    const [now, setNow] = useState(dayjs())
    const [showModal, setShowModal] = useState(false)

    useEffect(() => {
        const interval = window.setInterval(() => setNow(dayjs()), 1000)
        return () => {
            window.clearInterval(interval)
        }
    }, [])

    const { featureFlags } = useValues(featureFlagLogic)

    const expired = now.isSameOrAfter(endDate)

    if (expired || (now.isBefore(startDate) && !featureFlags[FEATURE_FLAGS.DWH_FREE_SYNCS])) {
        return <></>
    }

    const remainingMs = Math.max(0, endDate.diff(now))
    const totalSeconds = Math.floor(remainingMs / 1000)
    const days = Math.floor(totalSeconds / 86400)
    const hours = Math.floor((totalSeconds % 86400) / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const seconds = totalSeconds % 60

    return (
        <>
            <LemonBanner
                type="info"
                dismissKey="data-warehouse-free-syncs-2025"
                hideIcon={true}
                className="min-h-[auto]"
                onClose={() => {
                    posthog.capture('dwh_free_sync_banner_dismissed')
                }}
            >
                <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-1.5">
                        <strong className="font-bold text-sm">Free historical data syncs for 7 days!</strong>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                        <div
                            role="timer"
                            aria-live="polite"
                            className="flex items-center text-xs font-mono gap-1"
                            aria-label={`Time remaining: ${days} days, ${hours} hours, ${minutes} minutes, ${seconds} seconds`}
                        >
                            <span className="text-xs opacity-70">Ends:</span>
                            <span className="px-1 py-0.5 bg-bg-light rounded font-semibold">{days}d</span>
                            <span className="px-1 py-0.5 bg-bg-light rounded font-semibold">{pad(hours)}h</span>
                            <span className="px-1 py-0.5 bg-bg-light rounded font-semibold">{pad(minutes)}m</span>
                            <span className="px-1 py-0.5 bg-bg-light rounded font-semibold">{pad(seconds)}s</span>
                        </div>

                        <LemonButton
                            type="primary"
                            size="xsmall"
                            onClick={() => {
                                posthog.capture('dwh_free_sync_banner_learn_more_clicked')
                                setShowModal(true)
                            }}
                        >
                            Learn more
                        </LemonButton>
                    </div>
                </div>
            </LemonBanner>

            <LemonModal
                isOpen={showModal}
                onClose={() => setShowModal(false)}
                title="Free historical data syncs"
                width={600}
                footer={
                    <div className="flex items-center justify-between gap-2 w-full">
                        <Link
                            to="https://posthog.com/docs/cdp/sources"
                            target="_blank"
                            onClick={() => {
                                posthog.capture('dwh_free_sync_banner_docs_link_clicked')
                            }}
                        >
                            View documentation
                        </Link>
                        <LemonButton
                            type="primary"
                            to={urls.dataWarehouseSourceNew()}
                            onClick={() => {
                                posthog.capture('dwh_free_sync_banner_get_started_clicked')
                                setShowModal(false)
                            }}
                        >
                            Get started
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-4">
                    <p>
                        We've just reduced our data warehouse pricing and want to celebrate with you! For the next 7
                        days, all data warehouse syncs are completely free.
                    </p>

                    <div className="bg-bg-light rounded p-4">
                        <h4 className="text-sm font-semibold mb-2">What does this mean for you?</h4>
                        <ul className="space-y-2 text-sm list-disc list-inside">
                            <li>Import historical data from your production databases</li>
                            <li>Sync data from third-party services like Stripe, Google Ads, and BigQuery</li>
                            <li>
                                <strong>Paid plans:</strong> Unlimited rows during the free period
                            </li>
                            <li>
                                <strong>Free plan:</strong> Up to 100M rows during the free period
                            </li>
                            <li>All syncs are free until {endDate.format('MMMM D, YYYY')}</li>
                        </ul>
                    </div>

                    <div>
                        <h4 className="text-sm font-semibold mb-2">Ready to get started?</h4>
                        <p className="text-sm mb-2">
                            Click "Get started" below to add a new data source, or check out our documentation to learn
                            more about connecting your databases and third-party services.
                        </p>
                    </div>

                    <p className="text-sm opacity-70">
                        After the promotion ends, standard data warehouse pricing will apply.
                    </p>
                </div>
            </LemonModal>
        </>
    )
}
