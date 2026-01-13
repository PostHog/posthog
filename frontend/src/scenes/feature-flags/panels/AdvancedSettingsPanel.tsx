import { useActions, useValues } from 'kea'
import { Group } from 'kea-forms'

import { IconGlobe, IconLaptop, IconServer, IconTrash } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { FeatureFlagEvaluationRuntime } from '~/types'

import { JSONEditorInput } from '../JSONEditorInput'
import { featureFlagLogic } from '../featureFlagLogic'

export function AdvancedSettingsPanel(): JSX.Element {
    const { featureFlag, hasEncryptedPayloadBeenSaved, multivariateEnabled } = useValues(featureFlagLogic)
    const { resetEncryptedPayload } = useActions(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)

    const isNewFlag = featureFlag?.id === null

    // Safety check - if featureFlag is not loaded yet, show nothing
    if (!featureFlag) {
        return <div>Loading...</div>
    }

    const confirmEncryptedPayloadReset = (): void => {
        LemonDialog.open({
            title: 'Reset payload?',
            description: 'The existing payload will not be reset until the feature flag is saved.',
            primaryButton: {
                children: 'Reset',
                onClick: resetEncryptedPayload,
                size: 'small',
                status: 'danger',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    return (
        <div className="space-y-4">
            {/* Payload - only for non-multivariate flags */}
            {!multivariateEnabled && (
                <>
                    <SceneSection title="Payload (optional)">
                        <div className="text-secondary text-sm mb-4">
                            {featureFlag.is_remote_configuration ? (
                                <>
                                    Specify a valid JSON payload to be returned for the config flag. Read more in the{' '}
                                    <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads">
                                        payload documentation
                                    </Link>
                                    .
                                </>
                            ) : (
                                <>
                                    Return custom data with this flag. Useful for remote configuration. Optionally
                                    specify a valid JSON payload to be returned when the served value is{' '}
                                    <strong>
                                        <code>true</code>
                                    </strong>
                                    . Read more in the{' '}
                                    <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads">
                                        payload documentation
                                    </Link>
                                    .
                                </>
                            )}
                        </div>
                        {featureFlag.is_remote_configuration && (
                            <LemonField name="has_encrypted_payloads">
                                {({ value, onChange }) => (
                                    <div className="border rounded mb-4 p-4">
                                        <LemonCheckbox
                                            id="flag-payload-encrypted-checkbox"
                                            label="Encrypt remote configuration payload"
                                            onChange={() => onChange(!value)}
                                            checked={value}
                                            data-attr="feature-flag-payload-encrypted-checkbox"
                                            disabledReason={
                                                hasEncryptedPayloadBeenSaved &&
                                                'An encrypted payload has already been saved for this flag. Reset the payload or create a new flag to create an unencrypted configuration payload.'
                                            }
                                        />
                                    </div>
                                )}
                            </LemonField>
                        )}
                        <div className="flex gap-2">
                            <Group name={['filters', 'payloads']}>
                                <LemonField name="true" className="grow">
                                    <JSONEditorInput
                                        readOnly={
                                            featureFlag.has_encrypted_payloads &&
                                            Boolean(featureFlag.filters?.payloads?.['true'])
                                        }
                                        placeholder={'Examples: "A string", 2500, {"key": "value"}'}
                                    />
                                </LemonField>
                            </Group>
                            {featureFlag.has_encrypted_payloads && (
                                <LemonButton
                                    className="grow-0"
                                    icon={<IconTrash />}
                                    type="secondary"
                                    size="small"
                                    status="danger"
                                    onClick={confirmEncryptedPayloadReset}
                                >
                                    Reset
                                </LemonButton>
                            )}
                        </div>
                        {featureFlag.is_remote_configuration && (
                            <div className="text-sm text-secondary mt-4">
                                Note: remote config flags must be accessed through payloads, e.g.{' '}
                                <span className="font-mono font-bold">
                                    {featureFlag.has_encrypted_payloads
                                        ? 'getRemoteConfigPayload'
                                        : 'getFeatureFlagPayload'}
                                </span>
                                . Using standard SDK methods such as{' '}
                                <span className="font-mono font-bold">getFeatureFlag</span> or{' '}
                                <span className="font-mono font-bold">isFeatureEnabled</span> will always return{' '}
                                <span className="font-mono font-bold">true</span>
                            </div>
                        )}
                    </SceneSection>
                    <SceneDivider />
                </>
            )}

            {/* Evaluation runtime */}
            {featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_RUNTIMES] && (
                <>
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
                    <SceneDivider />
                </>
            )}

            {/* Persist flag across authentication */}
            {!featureFlag.is_remote_configuration && (
                <>
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
                                    Keep flag value consistent when anonymous users log in. If your feature flag is
                                    applied before identifying the user, use this to ensure that the flag value remains
                                    consistent for the same user. Depending on your setup, this option might not always
                                    be suitable. This feature requires creating profiles for anonymous users.{' '}
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
                    <SceneDivider />
                </>
            )}

            {/* Create usage dashboard - only for new flags */}
            {isNewFlag && (
                <LemonField name="_should_create_usage_dashboard">
                    {({ value, onChange }) => (
                        <div className="border rounded p-4">
                            <LemonCheckbox
                                id="create-usage-dashboard-checkbox"
                                label="Create usage dashboard"
                                onChange={() => onChange(!value)}
                                checked={value}
                                data-attr="create-usage-dashboard-checkbox"
                            />
                            <div className="text-secondary text-sm pl-7">
                                Automatically track flag calls and create an insights dashboard. This helps you monitor
                                how often this flag is called and what values are returned. Creates a dashboard with call
                                volume trends and variant distribution insights.
                            </div>
                        </div>
                    )}
                </LemonField>
            )}
        </div>
    )
}
