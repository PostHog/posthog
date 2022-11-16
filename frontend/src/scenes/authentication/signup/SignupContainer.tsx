import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { SignupForm } from './signupForm/control/SignupForm'
import { SignupForm as SignupFormTest } from './signupForm/test/SignupForm'

export const scene: SceneExport = {
    component: SignupContainer,
}

export function SignupContainer(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

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
            message={
                <>
                    Welcome to
                    <br /> PostHog{preflight?.cloud ? ' Cloud' : ''}!
                </>
            }
            footer={
                <>
                    {footerHighlights[preflight?.cloud ? 'cloud' : 'selfHosted'].map((val, idx) => (
                        <span key={idx} className="text-center">
                            {val}
                        </span>
                    ))}
                </>
            }
            sideLogo={featureFlags[FEATURE_FLAGS.SIGNUP_FORM_EXPERIMENT] !== 'test'}
            showSignupCta={preflight?.cloud}
        >
            {featureFlags[FEATURE_FLAGS.SIGNUP_FORM_EXPERIMENT] === 'test' ? <SignupFormTest /> : <SignupForm />}
        </BridgePage>
    ) : null
}
