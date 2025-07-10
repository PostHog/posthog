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
                <div className="relative mr-2 flex-shrink-0">
                    <LemonTag type="completion" className="absolute left-0 top-2.5 -rotate-12 transform">
                        EARLY ACCESS
                    </LemonTag>
                    <BuilderHog3 className="mt-6 h-20 w-20" />
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
                    <ul className="list-inside list-disc pl-2">
                        <li>Usage data updates daily (UTC) - so today's numbers show up tomorrow</li>
                        <li>Historical spend is calculated using the current subscription plan</li>
                    </ul>
                </div>
            </div>
        </LemonBanner>
    )
}
