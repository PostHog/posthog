import { useValues } from 'kea'
import { router } from 'kea-router'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { CLOUD_HOSTNAMES, FEATURE_FLAGS } from 'lib/constants'
import { IconCheckCircleOutline } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { Region } from '~/types'

import { SignupForm } from './signupForm/SignupForm'

export const scene: SceneExport = {
    component: SignupContainer,
}

export function SignupContainer(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)

    const footerHighlights = {
        cloud: ['Hosted & managed by PostHog', 'Pay per event, cancel anytime', 'Community, Slack & email support'],
        selfHosted: [
            'Fully featured product, unlimited events',
            'Data in your own infrastructure',
            'Community, Slack & email support',
        ],
    }

    return !user ? (
        <BridgePage
            view="signup"
            footer={
                <>
                    {footerHighlights[preflight?.cloud ? 'cloud' : 'selfHosted'].map((val, idx) => (
                        <span key={idx} className="text-center">
                            {val}
                        </span>
                    ))}
                </>
            }
            sideLogo
            leftContainerContent={<SignupLeftContainer />}
        >
            <SignupForm />
        </BridgePage>
    ) : null
}

export function SignupLeftContainer(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showGenericSignupBenefits: boolean = featureFlags[FEATURE_FLAGS.GENERIC_SIGNUP_BENEFITS] === 'test'

    const getRegionUrl = (region: string): string => {
        const { pathname, search, hash } = router.values.currentLocation
        return `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
    }

    const productBenefits: {
        benefit: string
        description: string
    }[] = showGenericSignupBenefits
        ? [
              {
                  benefit: 'Free usage every month - even on paid plans',
                  description: '1M free events, 15K free session recordings, and more. Every month. Forever.',
              },
              {
                  benefit: 'Start collecting data immediately',
                  description: 'Integrate with developer-friendly APIs or low-code web snippet.',
              },
              {
                  benefit: 'Join industry leaders that run on PostHog',
                  description:
                      'ClickHouse, Airbus, Hasura, Y Combinator, and thousands more trust PostHog as their Product OS.',
              },
          ]
        : [
              {
                  benefit: 'Free for 1M events every month',
                  description: 'Product analytics, feature flags, experiments, and more.',
              },
              {
                  benefit: 'Start collecting events immediately',
                  description: 'Integrate with developer-friendly APIs or use our easy autocapture script.',
              },
              {
                  benefit: 'Join industry leaders that run on PostHog',
                  description:
                      'ClickHouse, Airbus, Hasura, Y Combinator, and thousands more trust PostHog as their Product OS.',
              },
          ]

    return (
        <>
            <div className="mb-16 max-w-100">
                {productBenefits.map((benefit, i) => (
                    <div className="flex flex-row gap-4 mb-4" key={i}>
                        <div>
                            <IconCheckCircleOutline className="mt-2 w-4 h-4 text-link" />
                        </div>
                        <div>
                            <h3 className="mb-1 font-bold leading-6">{benefit.benefit}</h3>
                            <p className="m-0 text-sm">{benefit.description}</p>
                        </div>
                    </div>
                ))}
            </div>
            <div className="BridgePage__cta border rounded p-4 mt-8 text-center">
                Did you know?
                {preflight?.cloud ? (
                    <span>
                        {' '}
                        You can use our{' '}
                        <Link to={getRegionUrl(preflight?.region === Region.EU ? Region.US : Region.EU)}>
                            <strong>PostHog Cloud {preflight?.region === Region.EU ? 'US' : 'EU'}</strong>
                        </Link>
                        {preflight?.region === Region.EU ? ', too' : ' for a GDPR-ready deployment'}.
                    </span>
                ) : (
                    <span>
                        {' '}
                        You can use our{' '}
                        <Link to={getRegionUrl(Region.EU)}>
                            <strong>{Region.EU} cloud</strong>
                        </Link>{' '}
                        or{' '}
                        <Link to={getRegionUrl(Region.US)}>
                            <strong>{Region.US} cloud</strong>
                        </Link>{' '}
                        and we'll take care of the hosting for you.
                    </span>
                )}
            </div>
        </>
    )
}
