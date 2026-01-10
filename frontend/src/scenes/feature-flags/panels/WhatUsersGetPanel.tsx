import { useActions, useValues } from 'kea'
import { Group } from 'kea-forms'

import { IconTrash } from '@posthog/icons'
import { LemonDialog, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { FeatureFlagVariantsForm, focusVariantKeyField } from '../FeatureFlagVariantsForm'
import { JSONEditorInput } from '../JSONEditorInput'
import { featureFlagLogic } from '../featureFlagLogic'

export function WhatUsersGetPanel(): JSX.Element {
    const {
        multivariateEnabled,
        variants,
        nonEmptyVariants,
        aggregationTargetName,
        featureFlag,
        flagType,
        hasEncryptedPayloadBeenSaved,
        hasExperiment,
        isDraftExperiment,
        variantErrors,
        experiment,
    } = useValues(featureFlagLogic)
    const {
        distributeVariantsEqually,
        addVariant,
        removeVariant,
        setMultivariateEnabled,
        setFeatureFlag,
        setRemoteConfigEnabled,
        resetEncryptedPayload,
    } = useActions(featureFlagLogic)

    const filterGroups = featureFlag.filters.groups || []

    const confirmRevertMultivariateEnabled = (): void => {
        LemonDialog.open({
            title: 'Change value type?',
            description: 'The existing variants will be lost',
            primaryButton: {
                children: 'Confirm',
                type: 'primary',
                onClick: () => setMultivariateEnabled(false),
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
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

    const canEditVariant = (index: number): boolean => {
        if (hasExperiment && !isDraftExperiment) {
            return false
        }
        if (hasExperiment && isDraftExperiment && index === 0) {
            return false
        }
        return true
    }

    return (
        <div className="space-y-4">
            <SceneSection title="Served value">
                <div data-attr="feature-flag-served-value-segmented-button">
                    <LemonSegmentedButton
                        size="small"
                        options={[
                            {
                                label: 'Release toggle (boolean)',
                                value: 'boolean',
                                disabledReason: hasExperiment
                                    ? 'This feature flag is associated with an experiment.'
                                    : undefined,
                            },
                            {
                                label: <span>Multiple variants with rollout percentages (A/B/n test)</span>,
                                value: 'multivariate',
                            },
                            {
                                label: <span>Remote config (single payload)</span>,
                                value: 'remote_config',
                                disabledReason: hasExperiment
                                    ? 'This feature flag is associated with an experiment.'
                                    : undefined,
                            },
                        ]}
                        onChange={(value) => {
                            if (['boolean', 'remote_config'].includes(value) && nonEmptyVariants.length) {
                                confirmRevertMultivariateEnabled()
                            } else {
                                setMultivariateEnabled(value === 'multivariate')
                                setRemoteConfigEnabled(value === 'remote_config')
                                focusVariantKeyField(0)
                            }
                        }}
                        value={flagType}
                    />
                </div>
                <div className="text-secondary text-sm mt-2">
                    {featureFlag.is_remote_configuration ? (
                        <span>
                            Remote config flags provide runtime configuration values in your app. Read more in the{' '}
                            <Link to="https://posthog.com/docs/feature-flags/remote-config">
                                remote config flags documentation
                            </Link>
                            .
                        </span>
                    ) : (
                        <>
                            {capitalizeFirstLetter(aggregationTargetName)} will be served{' '}
                            {multivariateEnabled ? (
                                <>
                                    <strong>a variant key</strong> according to the below distribution
                                </>
                            ) : (
                                <strong>
                                    <code>true</code>
                                </strong>
                            )}{' '}
                            <span>if they match one or more release condition groups.</span>
                        </>
                    )}
                </div>
            </SceneSection>

            {!multivariateEnabled && (
                <>
                    <SceneDivider />
                    <SceneSection title="Payload">
                        <div className="w-1/2">
                            <div className="text-secondary mb-4">
                                {featureFlag.is_remote_configuration ? (
                                    <>
                                        Specify a valid JSON payload to be returned for the config flag. Read more in
                                        the{' '}
                                        <Link to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads">
                                            payload documentation
                                        </Link>
                                        .
                                    </>
                                ) : (
                                    <>
                                        Optionally specify a valid JSON payload to be returned when the served value is{' '}
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
                        </div>
                    </SceneSection>
                </>
            )}

            {multivariateEnabled && (
                <>
                    <LemonDivider className="my-0" />
                    <SceneSection
                        title="Variant keys"
                        description="The rollout percentage of feature flag variants must add up to 100%"
                    >
                        <FeatureFlagVariantsForm
                            variants={variants}
                            payloads={featureFlag.filters?.payloads}
                            filterGroups={filterGroups}
                            onAddVariant={addVariant}
                            onRemoveVariant={removeVariant}
                            onDistributeEqually={distributeVariantsEqually}
                            canEditVariant={canEditVariant}
                            hasExperiment={hasExperiment ?? false}
                            experimentId={experiment?.id}
                            experimentName={experiment?.name}
                            isDraftExperiment={isDraftExperiment}
                            onVariantChange={(index, field, value) => {
                                const currentVariants = [...variants]
                                currentVariants[index] = { ...currentVariants[index], [field]: value }
                                setFeatureFlag({
                                    ...featureFlag,
                                    filters: {
                                        ...featureFlag.filters,
                                        multivariate: {
                                            ...featureFlag.filters.multivariate,
                                            variants: currentVariants,
                                        },
                                    },
                                })
                            }}
                            onPayloadChange={(index, value) => {
                                const currentPayloads = { ...featureFlag.filters.payloads }
                                if (value === undefined) {
                                    delete currentPayloads[index]
                                } else {
                                    currentPayloads[index] = value
                                }
                                setFeatureFlag({
                                    ...featureFlag,
                                    filters: {
                                        ...featureFlag.filters,
                                        payloads: currentPayloads,
                                    },
                                })
                            }}
                            surveys={featureFlag.surveys ?? []}
                            variantErrors={variantErrors}
                        />
                    </SceneSection>
                </>
            )}
        </div>
    )
}
