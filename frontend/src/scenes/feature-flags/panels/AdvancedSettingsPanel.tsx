import { useValues } from 'kea'

import { IconGlobe, IconLaptop, IconServer } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { FeatureFlagEvaluationRuntime } from '~/types'

import { featureFlagLogic } from '../featureFlagLogic'

export function AdvancedSettingsPanel(): JSX.Element {
    const { featureFlag } = useValues(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)

    return (
        <div className="space-y-4">
            {!featureFlag.is_remote_configuration && (
                <LemonField name="ensure_experience_continuity">
                    {({ value, onChange }) => (
                        <div className="border rounded p-4">
                            <LemonCheckbox
                                id="continuity-checkbox"
                                label="Persist flag across authentication steps"
                                onChange={() => onChange(!value)}
                                fullWidth
                                checked={value}
                            />
                            <div className="text-secondary text-sm pl-7">
                                If your feature flag is applied before identifying the user, use this to ensure that the
                                flag value remains consistent for the same user. Depending on your setup, this option
                                might not always be suitable. This feature requires creating profiles for anonymous
                                users.{' '}
                                <Link
                                    to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                                    target="_blank"
                                >
                                    Learn more
                                </Link>
                            </div>
                        </div>
                    )}
                </LemonField>
            )}

            {featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES] && (
                <>
                    {!featureFlag.is_remote_configuration && <SceneDivider />}
                    <SceneSection title="Evaluation runtime">
                        <div className="text-secondary text-sm mb-2">
                            This setting controls where your feature flag can be evaluated. If you try to use a flag in
                            a runtime where it's not allowed (e.g., using a server-only flag in client-side code), it
                            won't evaluate.{' '}
                            <Link
                                to="https://posthog.com/docs/feature-flags/evaluation-environments"
                                target="_blank"
                                targetBlankIcon
                            >
                                Learn more about using evaluation environments
                            </Link>
                        </div>
                        <LemonField name="evaluation_runtime">
                            {({ value, onChange }) => (
                                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                                    {[
                                        {
                                            value: FeatureFlagEvaluationRuntime.ALL,
                                            icon: <IconGlobe />,
                                            title: 'Both client and server',
                                            description: 'Single-user apps + multi-user systems',
                                        },
                                        {
                                            value: FeatureFlagEvaluationRuntime.CLIENT,
                                            icon: <IconLaptop />,
                                            title: 'Client-side only',
                                            description: 'Single-user apps (mobile, desktop, embedded)',
                                        },
                                        {
                                            value: FeatureFlagEvaluationRuntime.SERVER,
                                            icon: <IconServer />,
                                            title: 'Server-side only',
                                            description: 'Multi-user systems in trusted environments',
                                        },
                                    ].map((option) => (
                                        <div
                                            key={option.value}
                                            className={`border rounded-lg p-4 cursor-pointer transition-all hover:border-primary-light ${
                                                value === option.value
                                                    ? 'border-primary bg-primary-highlight'
                                                    : 'border-border'
                                            }`}
                                            onClick={() => onChange(option.value)}
                                        >
                                            <div className="flex items-start gap-3">
                                                <div className="text-lg text-muted">{option.icon}</div>
                                                <div className="flex-1">
                                                    <div className="font-medium text-sm">{option.title}</div>
                                                    <div className="text-xs text-muted mt-1">{option.description}</div>
                                                </div>
                                                <input
                                                    type="radio"
                                                    name="evaluation-environment"
                                                    checked={value === option.value}
                                                    onChange={() => onChange(option.value)}
                                                    className="cursor-pointer"
                                                />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </LemonField>
                    </SceneSection>
                </>
            )}
        </div>
    )
}
