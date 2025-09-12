import { useActions } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'

export function BillingEarlyAccessBanner(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <LemonBanner type="info" hideIcon className="overflow-visible">
            <div className="flex items-center gap-4">
                <div className="relative flex-shrink-0 mr-2">
                    <LemonTag type="completion" className="absolute top-2.5 left-0 transform -rotate-12">
                        EARLY ACCESS
                    </LemonTag>
                    <BuilderHog3 className="w-20 h-20 mt-6" />
                </div>
                <div className="text-primary">
                    <p>
                        We're still tinkering with these dashboards - got questions, ideas or bugs?{' '}
                        <Link
                            onClick={() =>
                                openSupportForm({
                                    kind: 'support',
                                    target_area: 'billing',
                                    isEmailFormOpen: true,
                                })
                            }
                        >
                            Send them our way
                        </Link>
                        !
                    </p>
                    <ul className="list-disc list-inside pl-2">
                        <li>Usage data updates daily (UTC) - so today's numbers show up tomorrow</li>
                        <li>Historical spend and billing periods are based on the current subscription plan</li>
                        <li>
                            To further breakdown product usage, check out this{' '}
                            <Link
                                to={`/dashboard?templateFilter=${encodeURIComponent('billable usage')}#newDashboard=modal`}
                            >
                                dashboard template
                            </Link>
                        </li>
                    </ul>
                </div>
            </div>
        </LemonBanner>
    )
}
