import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { router } from 'kea-router'
import { useRef } from 'react'

import {
    IconBalance,
    IconCode,
    IconFlag,
    IconGlobe,
    IconInfo,
    IconList,
    IconPlus,
    IconServer,
    IconTrash,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
    Lettermark,
    LettermarkColor,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import 'lib/lemon-ui/Lettermark'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { alphabet } from 'lib/utils'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { FeatureFlagBucketingIdentifier, FeatureFlagEvaluationRuntime } from '~/types'

import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import { FeatureFlagEvaluationTags } from './FeatureFlagEvaluationTags'
import { FeatureFlagLogicProps, featureFlagLogic, slugifyFeatureFlagKey } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

export function FeatureFlagForm({ id }: FeatureFlagLogicProps): JSX.Element {
    const {
        props,
        featureFlag,
        originalFeatureFlag,
        multivariateEnabled,
        variants,
        nonEmptyVariants,
        variantErrors,
        isEditingFlag,
        showImplementation,
        openVariants,
        payloadExpanded,
    } = useValues(featureFlagLogic)
    const {
        setMultivariateEnabled,
        setFeatureFlag,
        addVariant,
        removeVariant,
        distributeVariantsEqually,
        setFeatureFlagFilters,
        editFeatureFlag,
        loadFeatureFlag,
        setShowImplementation,
        setOpenVariants,
        setPayloadExpanded,
        setBucketingIdentifier,
    } = useActions(featureFlagLogic)
    const { tags: availableTags } = useValues(tagsModel)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const hasEvaluationTags = useFeatureFlag('FLAG_EVALUATION_TAGS')
    const featureFlagsV2Enabled = !!featureFlags[FEATURE_FLAGS.FEATURE_FLAGS_V2]
    const showBucketingIdentifierUI = !!featureFlags[FEATURE_FLAGS.FLAG_BUCKETING_IDENTIFIER]

    const isNewFeatureFlag = id === 'new' || id === undefined
    const implementationRef = useRef<HTMLDivElement>(null)

    const handleShowImplementation = (): void => {
        setShowImplementation(true)
        setTimeout(() => {
            implementationRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }, 150)
    }

    const updateVariant = (
        index: number,
        field: 'key' | 'name' | 'rollout_percentage',
        value: string | number
    ): void => {
        const coercedValue = field === 'rollout_percentage' ? Number(value) || 0 : String(value)
        const currentVariants = [...variants]
        const oldKey = currentVariants[index]?.key
        currentVariants[index] = { ...currentVariants[index], [field]: coercedValue }

        // If the key is being changed, migrate any existing payload to the new key
        let updatedPayloads = { ...featureFlag?.filters?.payloads }
        if (field === 'key' && oldKey && oldKey !== coercedValue) {
            const existingPayload = updatedPayloads[oldKey]
            if (existingPayload !== undefined) {
                delete updatedPayloads[oldKey]
                updatedPayloads[coercedValue as string] = existingPayload
            }
        }

        setFeatureFlag({
            ...featureFlag,
            filters: {
                ...featureFlag?.filters,
                multivariate: {
                    ...featureFlag?.filters?.multivariate,
                    variants: currentVariants,
                },
                payloads: updatedPayloads,
            },
        })
    }

    const updateVariantPayload = (index: number, value: string | undefined): void => {
        const variantKey = variants[index]?.key
        if (!variantKey) {
            return
        }
        const currentPayloads = { ...featureFlag?.filters?.payloads }
        if (value === '' || value === undefined) {
            delete currentPayloads[variantKey]
        } else {
            currentPayloads[variantKey] = value
        }
        setFeatureFlag({
            ...featureFlag,
            filters: {
                ...featureFlag?.filters,
                payloads: currentPayloads,
            },
        })
    }

    if (!featureFlag) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }
    return (
        <>
            <Form
                id="feature-flag"
                logic={featureFlagLogic}
                props={props}
                formKey="featureFlag"
                enableFormOnSubmit
                className="deprecated-space-y-4"
            >
                <SceneTitleSection
                    name={featureFlag.key || 'New feature flag'}
                    resourceType={{
                        type: featureFlag.active ? 'feature_flag' : 'feature_flag_off',
                    }}
                    forceBackTo={
                        isNewFeatureFlag && featureFlagsV2Enabled
                            ? { key: 'FeatureFlagTemplates', name: 'Templates', path: urls.featureFlagTemplates() }
                            : undefined
                    }
                    actions={
                        <>
                            <LemonButton
                                data-attr="cancel-feature-flag"
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    if (isEditingFlag) {
                                        editFeatureFlag(false)
                                        loadFeatureFlag()
                                    } else {
                                        router.actions.push(urls.featureFlags())
                                    }
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="save-feature-flag"
                                htmlType="submit"
                                form="feature-flag"
                                size="small"
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                />

                <SceneContent>
                    {/* Two-column layout */}
                    <div className="flex gap-4 flex-wrap items-start">
                        {/* Left column */}
                        <div className="flex-1 min-w-[20rem] flex flex-col gap-4">
                            {/* Main settings card */}
                            <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
                                <LemonField
                                    name="key"
                                    label="Flag key"
                                    info="Unique identifier used in your code."
                                    help={
                                        !isNewFeatureFlag &&
                                        originalFeatureFlag &&
                                        featureFlag.key !== originalFeatureFlag.key ? (
                                            <span className="text-warning">
                                                <b>Warning! </b>Changing this key will break any existing code that
                                                references it (e.g.{' '}
                                                <code className="text-xs bg-fill-secondary rounded px-1 py-0.5">
                                                    getFeatureFlag('{originalFeatureFlag.key}')
                                                </code>
                                                ). Make sure to update all SDK calls and integrations.
                                            </span>
                                        ) : undefined
                                    }
                                >
                                    {({ value, onChange }) => (
                                        <LemonInput
                                            value={value}
                                            onChange={(v) => onChange(slugifyFeatureFlagKey(v))}
                                            data-attr="feature-flag-key"
                                            className="ph-ignore-input"
                                            autoComplete="off"
                                            autoCapitalize="off"
                                            autoCorrect="off"
                                            spellCheck={false}
                                            placeholder="Enter a unique key - e.g. new-landing-page, betaFeature, ab_test_1"
                                        />
                                    )}
                                </LemonField>

                                <LemonField name="name" label="Description">
                                    <LemonTextArea
                                        className="ph-ignore-input"
                                        data-attr="feature-flag-description"
                                        placeholder="(Optional) A description of the feature flag for your reference."
                                    />
                                </LemonField>

                                <LemonDivider />

                                <LemonField name="active">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            checked={value}
                                            onChange={onChange}
                                            label={
                                                <span className="flex items-center gap-1">
                                                    <span>Enabled</span>
                                                    <Tooltip title="When disabled, all SDKs return false without checking release conditions.">
                                                        <IconInfo className="text-secondary text-base" />
                                                    </Tooltip>
                                                </span>
                                            }
                                            bordered
                                            fullWidth
                                            data-attr="feature-flag-enabled"
                                        />
                                    )}
                                </LemonField>
                            </div>

                            {/* Advanced options - collapsed by default */}
                            <LemonCollapse
                                className="bg-bg-light"
                                panels={[
                                    {
                                        key: 'advanced',
                                        header: {
                                            children: (
                                                <div className="py-1">
                                                    <div className="font-semibold">Advanced options</div>
                                                    <div className="text-secondary text-sm font-normal">
                                                        Tags, evaluation contexts, runtime settings, and persistence.
                                                    </div>
                                                </div>
                                            ),
                                        },
                                        content: (
                                            <div className="flex flex-col gap-4">
                                                {/* Tags section */}
                                                <div className="flex flex-col gap-2">
                                                    <label className="text-sm font-medium flex items-center gap-1">
                                                        {hasEvaluationTags ? 'Tags & evaluation contexts' : 'Tags'}
                                                        <Tooltip
                                                            title={
                                                                hasEvaluationTags ? (
                                                                    <>
                                                                        Use tags to organize flags. Mark a tag as an
                                                                        evaluation context to restrict where this flag
                                                                        can evaluate.{' '}
                                                                        <Link
                                                                            to="https://posthog.com/docs/feature-flags/evaluation-contexts"
                                                                            target="_blank"
                                                                        >
                                                                            Learn more
                                                                        </Link>
                                                                    </>
                                                                ) : (
                                                                    'Organize and filter your flags.'
                                                                )
                                                            }
                                                            interactive={hasEvaluationTags}
                                                        >
                                                            <IconInfo className="text-secondary text-base" />
                                                        </Tooltip>
                                                    </label>
                                                    {hasEvaluationTags ? (
                                                        <LemonField name="tags">
                                                            {({ value: formTags, onChange: onChangeTags }) => (
                                                                <LemonField name="evaluation_tags">
                                                                    {({
                                                                        value: formEvalTags,
                                                                        onChange: onChangeEvalTags,
                                                                    }) => (
                                                                        <FeatureFlagEvaluationTags
                                                                            tags={formTags}
                                                                            evaluationTags={formEvalTags || []}
                                                                            context="form"
                                                                            onChange={(
                                                                                updatedTags,
                                                                                updatedEvaluationTags
                                                                            ) => {
                                                                                onChangeTags(updatedTags)
                                                                                onChangeEvalTags(updatedEvaluationTags)
                                                                            }}
                                                                            tagsAvailable={availableTags.filter(
                                                                                (tag: string) =>
                                                                                    !formTags?.includes(tag)
                                                                            )}
                                                                        />
                                                                    )}
                                                                </LemonField>
                                                            )}
                                                        </LemonField>
                                                    ) : (
                                                        <LemonField name="tags">
                                                            {({ value: formTags, onChange: onChangeTags }) => (
                                                                <ObjectTags
                                                                    tags={formTags}
                                                                    onChange={onChangeTags}
                                                                    saving={false}
                                                                    tagsAvailable={availableTags.filter(
                                                                        (tag: string) => !formTags?.includes(tag)
                                                                    )}
                                                                />
                                                            )}
                                                        </LemonField>
                                                    )}
                                                </div>

                                                <LemonDivider className="my-1" />

                                                {/* Evaluation runtime */}
                                                <LemonField
                                                    name="evaluation_runtime"
                                                    label="Evaluation runtime"
                                                    labelClassName="text-sm font-medium"
                                                    info={
                                                        <>
                                                            Control whether this flag evaluates on client, server, or
                                                            both.{' '}
                                                            <Link
                                                                to="https://posthog.com/docs/feature-flags/creating-feature-flags#step-5-configure-evaluation-runtime-and-environments-optional"
                                                                target="_blank"
                                                            >
                                                                Learn more
                                                            </Link>
                                                        </>
                                                    }
                                                >
                                                    <LemonSelect
                                                        fullWidth
                                                        options={[
                                                            {
                                                                label: (
                                                                    <div className="flex flex-col">
                                                                        <span className="font-medium">
                                                                            Both client and server
                                                                        </span>
                                                                        <span className="text-xs text-muted">
                                                                            Single-user apps + multi-user systems
                                                                        </span>
                                                                    </div>
                                                                ),
                                                                value: FeatureFlagEvaluationRuntime.ALL,
                                                                icon: <IconGlobe />,
                                                            },
                                                            {
                                                                label: (
                                                                    <div className="flex flex-col">
                                                                        <span className="font-medium">
                                                                            Client-side only
                                                                        </span>
                                                                        <span className="text-xs text-muted">
                                                                            Single-user apps (mobile, desktop, embedded)
                                                                        </span>
                                                                    </div>
                                                                ),
                                                                value: FeatureFlagEvaluationRuntime.CLIENT,
                                                                icon: <IconList />,
                                                            },
                                                            {
                                                                label: (
                                                                    <div className="flex flex-col">
                                                                        <span className="font-medium">
                                                                            Server-side only
                                                                        </span>
                                                                        <span className="text-xs text-muted">
                                                                            Multi-user systems in trusted environments
                                                                        </span>
                                                                    </div>
                                                                ),
                                                                value: FeatureFlagEvaluationRuntime.SERVER,
                                                                icon: <IconServer />,
                                                            },
                                                        ]}
                                                        data-attr="feature-flag-evaluation-runtime"
                                                    />
                                                </LemonField>

                                                <LemonDivider className="my-1" />

                                                {/* Persistence */}
                                                <LemonField
                                                    name="ensure_experience_continuity"
                                                    label="Persistence"
                                                    labelClassName="text-sm font-medium"
                                                    info={
                                                        <>
                                                            Keep flag values consistent before and after login. Requires
                                                            anonymous user profiles.{' '}
                                                            <Link
                                                                to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                                                                target="_blank"
                                                            >
                                                                Learn more
                                                            </Link>
                                                        </>
                                                    }
                                                >
                                                    {({ value, onChange }) => (
                                                        <LemonSwitch
                                                            checked={value}
                                                            onChange={onChange}
                                                            bordered
                                                            fullWidth
                                                            label="Persist flag across authentication steps"
                                                            data-attr="feature-flag-persist-across-auth"
                                                        />
                                                    )}
                                                </LemonField>
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        </div>

                        {/* Right column */}
                        <div className="flex-2 flex flex-col gap-4" style={{ minWidth: '30rem' }}>
                            {/* Flag type card */}
                            <div className="rounded border p-3 bg-bg-light gap-4 flex flex-col">
                                <div className="flex flex-col gap-2">
                                    <LemonLabel info="Changing type may remove existing variants or payloads.">
                                        Flag type
                                    </LemonLabel>
                                    <LemonSelect
                                        fullWidth
                                        value={
                                            featureFlag.is_remote_configuration
                                                ? 'remote_config'
                                                : multivariateEnabled
                                                  ? 'multivariate'
                                                  : 'boolean'
                                        }
                                        onChange={(value) => {
                                            if (value === 'remote_config') {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: true,
                                                })
                                                // setMultivariateEnabled(false) cleans up variant payloads via setMultivariateOptions(null)
                                                setMultivariateEnabled(false)
                                            } else if (value === 'multivariate') {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: false,
                                                    filters: {
                                                        ...featureFlag.filters,
                                                        // Clear boolean payload when switching to multivariate
                                                        payloads: {},
                                                    },
                                                })
                                                setMultivariateEnabled(true)
                                            } else {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: false,
                                                })
                                                // setMultivariateEnabled(false) cleans up variant payloads via setMultivariateOptions(null)
                                                setMultivariateEnabled(false)
                                            }
                                        }}
                                        options={[
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Boolean</span>
                                                        <span className="text-xs text-muted">
                                                            Release toggle (boolean) with optional static payload
                                                        </span>
                                                    </div>
                                                ),
                                                value: 'boolean',
                                                icon: <IconFlag />,
                                            },
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Multivariate</span>
                                                        <span className="text-xs text-muted">
                                                            Multiple variants with rollout percentages (A/B/n test)
                                                        </span>
                                                    </div>
                                                ),
                                                value: 'multivariate',
                                                icon: <IconList />,
                                            },
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Remote config</span>
                                                        <span className="text-xs text-muted">
                                                            Single payload without feature flag logic
                                                        </span>
                                                    </div>
                                                ),
                                                value: 'remote_config',
                                                icon: <IconCode />,
                                            },
                                        ]}
                                        data-attr="feature-flag-type"
                                    />
                                    <div className="text-secondary text-xs mt-1">
                                        {featureFlag.is_remote_configuration ? (
                                            <>
                                                Returns a JSON payload directly, without feature flag evaluation logic.
                                                Access it via <code className="text-xs">getFeatureFlagPayload</code>.
                                            </>
                                        ) : multivariateEnabled ? (
                                            <>
                                                When release conditions match, returns one of the variant keys (string)
                                                based on rollout percentages. Each variant can optionally include a JSON
                                                payload. Access the variant via{' '}
                                                <code className="text-xs">getFeatureFlag</code> and its payload via{' '}
                                                <code className="text-xs">getFeatureFlagPayload</code>.
                                            </>
                                        ) : (
                                            <>
                                                Returns <code className="text-xs">true</code> or{' '}
                                                <code className="text-xs">false</code> based on targeting rules. You can
                                                optionally attach a JSON payload that will be available on the flag when
                                                it evaluates to <code className="text-xs">true</code>.
                                            </>
                                        )}
                                    </div>
                                </div>

                                {/* Variants section - only for multivariate */}
                                {multivariateEnabled && (
                                    <div className="flex flex-col gap-2">
                                        <div className="flex items-center justify-between">
                                            <LemonLabel>Variants</LemonLabel>
                                            <LemonButton
                                                size="small"
                                                icon={<IconBalance />}
                                                onClick={distributeVariantsEqually}
                                                tooltip="Distribute rollout percentages equally"
                                            />
                                        </div>

                                        <LemonCollapse
                                            multiple
                                            activeKeys={openVariants}
                                            onChange={setOpenVariants}
                                            panels={variants.map((variant, index) => ({
                                                key: `variant-${index}`,
                                                header: (
                                                    <div className="flex gap-2 items-center">
                                                        <Lettermark
                                                            name={alphabet[index] ?? String(index + 1)}
                                                            color={LettermarkColor.Gray}
                                                            size="small"
                                                        />
                                                        <span className="text-sm font-medium">
                                                            {variant.key || `Variant ${index + 1}`}
                                                        </span>
                                                        <span className="text-xs text-muted">
                                                            ({variant.rollout_percentage || 0}%)
                                                        </span>
                                                    </div>
                                                ),
                                                content: (
                                                    <div className="flex flex-col gap-2">
                                                        <LemonLabel>Variant key</LemonLabel>
                                                        <LemonInput
                                                            placeholder="Enter a variant key - e.g. control, test, variant_1"
                                                            value={variant.key}
                                                            onChange={(value) => updateVariant(index, 'key', value)}
                                                            status={variantErrors[index]?.key ? 'danger' : undefined}
                                                            data-attr={`feature-flag-variant-key-${index}`}
                                                        />
                                                        {variantErrors[index]?.key && (
                                                            <span className="text-danger text-xs">
                                                                {variantErrors[index].key}
                                                            </span>
                                                        )}

                                                        <LemonLabel>Rollout percentage</LemonLabel>
                                                        <LemonInput
                                                            type="number"
                                                            min={0}
                                                            max={100}
                                                            value={variant.rollout_percentage || 0}
                                                            onChange={(value) =>
                                                                updateVariant(
                                                                    index,
                                                                    'rollout_percentage',
                                                                    parseInt(value?.toString() || '0')
                                                                )
                                                            }
                                                            suffix={<span>%</span>}
                                                            data-attr={`feature-flag-variant-rollout-${index}`}
                                                        />

                                                        <LemonLabel>Description</LemonLabel>
                                                        <LemonTextArea
                                                            placeholder="Enter an optional description for the variant"
                                                            value={variant.name || ''}
                                                            onChange={(value) => updateVariant(index, 'name', value)}
                                                            data-attr={`feature-flag-variant-description-${index}`}
                                                        />

                                                        <LemonLabel info="Optionally return JSON data when this variant matches.">
                                                            Payload
                                                        </LemonLabel>
                                                        <JSONEditorInput
                                                            onChange={(value) => updateVariantPayload(index, value)}
                                                            value={featureFlag.filters?.payloads?.[variant.key]}
                                                            placeholder='{"key": "value"}'
                                                        />

                                                        {variants.length > 1 && <LemonDivider />}
                                                        {variants.length > 1 && (
                                                            <LemonButton
                                                                type="secondary"
                                                                status="danger"
                                                                size="small"
                                                                icon={<IconTrash />}
                                                                onClick={() => {
                                                                    const variantKey =
                                                                        variant.key || `Variant ${index + 1}`
                                                                    const hasPayload =
                                                                        !!featureFlag.filters?.payloads?.[variant.key]
                                                                    LemonDialog.open({
                                                                        title: `Remove variant "${variantKey}"?`,
                                                                        description: hasPayload
                                                                            ? 'This variant has a payload configured. Both the variant and its payload will be deleted.'
                                                                            : 'This action cannot be undone.',
                                                                        primaryButton: {
                                                                            children: 'Remove variant',
                                                                            status: 'danger',
                                                                            onClick: () => removeVariant(index),
                                                                        },
                                                                        secondaryButton: {
                                                                            children: 'Cancel',
                                                                        },
                                                                    })
                                                                }}
                                                            >
                                                                Remove variant
                                                            </LemonButton>
                                                        )}
                                                    </div>
                                                ),
                                            }))}
                                        />

                                        <div>
                                            <LemonButton
                                                type="secondary"
                                                icon={<IconPlus />}
                                                onClick={addVariant}
                                                data-attr="feature-flag-add-variant"
                                            >
                                                Add variant
                                            </LemonButton>
                                        </div>
                                    </div>
                                )}

                                {/* Payload section - for boolean and remote config flags */}
                                {!multivariateEnabled && featureFlag.is_remote_configuration && (
                                    <div className="flex flex-col gap-2">
                                        <LemonLabel info="JSON data returned by this remote config.">
                                            Payload
                                        </LemonLabel>
                                        <div className="text-secondary text-xs mb-1">
                                            Remote config flags always return the payload. Access it via{' '}
                                            <code className="text-xs">getFeatureFlagPayload</code>.
                                        </div>
                                        <Group name={['filters', 'payloads']}>
                                            <LemonField name="true">
                                                <JSONEditorInput placeholder='Examples: "A string", 2500, {"key": "value"}' />
                                            </LemonField>
                                        </Group>
                                    </div>
                                )}
                                {!multivariateEnabled && !featureFlag.is_remote_configuration && (
                                    <LemonCollapse
                                        activeKeys={payloadExpanded ? ['payload'] : []}
                                        onChange={(keys) => setPayloadExpanded(keys?.includes('payload') ?? false)}
                                        panels={[
                                            {
                                                key: 'payload',
                                                header: 'Payload',
                                                content: (
                                                    <div className="flex flex-col gap-2">
                                                        <div className="text-secondary text-xs">
                                                            When the flag evaluates to{' '}
                                                            <code className="text-xs">true</code>, this payload will be
                                                            available via{' '}
                                                            <code className="text-xs">getFeatureFlagPayload</code>.{' '}
                                                            <Link
                                                                to="https://posthog.com/docs/feature-flags/creating-feature-flags#payloads"
                                                                target="_blank"
                                                            >
                                                                Learn more
                                                            </Link>
                                                        </div>
                                                        <Group name={['filters', 'payloads']}>
                                                            <LemonField name="true">
                                                                <JSONEditorInput placeholder='Examples: "A string", 2500, {"key": "value"}' />
                                                            </LemonField>
                                                        </Group>
                                                    </div>
                                                ),
                                            },
                                        ]}
                                    />
                                )}
                            </div>

                            {/* Release conditions card - skip for remote config */}
                            {!featureFlag.is_remote_configuration && (
                                <div className="rounded border p-3 bg-bg-light">
                                    <FeatureFlagReleaseConditionsCollapsible
                                        id={String(props.id)}
                                        filters={featureFlag.filters}
                                        onChange={setFeatureFlagFilters}
                                        variants={nonEmptyVariants}
                                        isDisabled={!featureFlag.active}
                                        bucketingIdentifier={
                                            showBucketingIdentifierUI ? featureFlag.bucketing_identifier : undefined
                                        }
                                        onBucketingIdentifierChange={
                                            showBucketingIdentifierUI
                                                ? (value: FeatureFlagBucketingIdentifier | null) =>
                                                      setBucketingIdentifier(value)
                                                : undefined
                                        }
                                    />
                                </div>
                            )}

                            {/* Implementation section */}
                            {showImplementation ? (
                                <div
                                    ref={implementationRef}
                                    className="rounded border p-3 bg-bg-light gap-2 flex flex-col mb-4"
                                >
                                    <LemonButton
                                        className="-m-2"
                                        icon={<IconCode />}
                                        onClick={() => setShowImplementation(false)}
                                    >
                                        Implementation
                                    </LemonButton>
                                    <LemonDivider />
                                    <FeatureFlagCodeExample featureFlag={featureFlag} />
                                </div>
                            ) : (
                                <div className="rounded border bg-bg-light gap-2 flex flex-col p-3 mb-4">
                                    <LemonButton
                                        className="-m-2"
                                        icon={<IconCode />}
                                        onClick={handleShowImplementation}
                                    >
                                        Show implementation
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    </div>
                </SceneContent>
            </Form>
        </>
    )
}
