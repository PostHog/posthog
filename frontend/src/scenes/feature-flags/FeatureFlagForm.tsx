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
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import 'lib/lemon-ui/Lettermark'
import { alphabet } from 'lib/utils'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { FeatureFlagEvaluationRuntime } from '~/types'

import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import { FeatureFlagEvaluationTags } from './FeatureFlagEvaluationTags'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import { FeatureFlagTemplates } from './FeatureFlagTemplates'
import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'

export function FeatureFlagForm({ id }: FeatureFlagLogicProps): JSX.Element {
    const {
        props,
        featureFlag,
        multivariateEnabled,
        variants,
        nonEmptyVariants,
        variantErrors,
        isEditingFlag,
        showImplementation,
        openVariants,
        payloadExpanded,
        highlightedFields,
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
        clearHighlight,
    } = useActions(featureFlagLogic)
    const { tags: availableTags } = useValues(tagsModel)
    const hasEvaluationTags = useFeatureFlag('FLAG_EVALUATION_TAGS')

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
                    {/* Templates - only show for new flags */}
                    {isNewFeatureFlag && <FeatureFlagTemplates />}

                    {/* Two-column layout */}
                    <div className="flex gap-4 flex-wrap items-start">
                        {/* Left column */}
                        <div className="flex-1 min-w-[20rem] flex flex-col gap-4">
                            {/* Main settings card */}
                            <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
                                <LemonField
                                    name="key"
                                    label="Flag key"
                                    info="The key is used to identify the feature flag in the code. Must be unique."
                                >
                                    {({ value, onChange }) => (
                                        <LemonInput
                                            value={value}
                                            onChange={(newValue) => {
                                                clearHighlight('key')
                                                onChange(newValue)
                                            }}
                                            data-attr="feature-flag-key"
                                            className={`ph-ignore-input ${highlightedFields.includes('key') ? 'template-highlight-glow' : ''}`}
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
                                        <Tooltip
                                            title="When enabled, this flag evaluates according to your release conditions. When disabled, this flag will not be evaluated and PostHog SDKs default to returning false."
                                            placement="top"
                                        >
                                            <LemonSwitch
                                                checked={value}
                                                onChange={onChange}
                                                label={
                                                    <span className="flex items-center">
                                                        <span>Enabled</span>
                                                        <IconInfo className="ml-1 text-lg" />
                                                    </span>
                                                }
                                                bordered
                                                fullWidth
                                                data-attr="feature-flag-enabled"
                                            />
                                        </Tooltip>
                                    )}
                                </LemonField>
                            </div>

                            {/* Tags card */}
                            <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
                                <LemonLabel
                                    info={
                                        hasEvaluationTags
                                            ? 'Use tags to organize flags. Mark tags as evaluation contexts to control when flags evaluate – flags only evaluate when the SDK provides matching environment tags.'
                                            : 'Use tags to organize and filter your feature flags.'
                                    }
                                >
                                    {hasEvaluationTags ? 'Tags & evaluation contexts' : 'Tags'}
                                </LemonLabel>
                                {hasEvaluationTags ? (
                                    <LemonField name="tags">
                                        {({ value: formTags, onChange: onChangeTags }) => (
                                            <LemonField name="evaluation_tags">
                                                {({ value: formEvalTags, onChange: onChangeEvalTags }) => (
                                                    <FeatureFlagEvaluationTags
                                                        tags={formTags}
                                                        evaluationTags={formEvalTags || []}
                                                        context="form"
                                                        onChange={(updatedTags, updatedEvaluationTags) => {
                                                            onChangeTags(updatedTags)
                                                            onChangeEvalTags(updatedEvaluationTags)
                                                        }}
                                                        tagsAvailable={availableTags.filter(
                                                            (tag: string) => !formTags?.includes(tag)
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

                            {/* Advanced options card */}
                            <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
                                <LemonLabel>Advanced options</LemonLabel>
                                <p className="text-xs text-muted mb-1">
                                    Control where and how this flag is evaluated. Most flags work fine with the
                                    defaults.
                                </p>

                                <LemonField
                                    name="evaluation_runtime"
                                    label="Evaluation runtime"
                                    labelClassName="font-medium"
                                    info={
                                        <>
                                            Controls where your feature flag can be evaluated. If you try to use a flag
                                            in a runtime where it's not allowed (e.g., using a server-only flag in
                                            client-side code), it won't evaluate.{' '}
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
                                                        <span className="font-medium">Both client and server</span>
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
                                                        <span className="font-medium">Client-side only</span>
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
                                                        <span className="font-medium">Server-side only</span>
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

                                <LemonField
                                    name="ensure_experience_continuity"
                                    label="Persistence"
                                    labelClassName="font-medium"
                                    info={
                                        <>
                                            If your feature flag is applied before identifying the user, use this to
                                            ensure that the flag value remains consistent for the same user. This
                                            requires creating profiles for anonymous users.{' '}
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
                        </div>

                        {/* Right column */}
                        <div className="flex-2 flex flex-col gap-4" style={{ minWidth: '30rem' }}>
                            {/* Flag type card */}
                            <div className="rounded border p-3 bg-bg-light gap-4 flex flex-col">
                                <div className="flex flex-col gap-2">
                                    <LemonLabel info="Changing flag type may clear existing configuration. Switching from Multivariate will remove all variants and their payloads. Switching from Remote config or Boolean will remove the payload.">
                                        Flag type
                                    </LemonLabel>
                                    <LemonSelect
                                        fullWidth
                                        className={
                                            highlightedFields.includes('flagType') ? 'template-highlight-glow' : ''
                                        }
                                        value={
                                            featureFlag.is_remote_configuration
                                                ? 'remote_config'
                                                : multivariateEnabled
                                                  ? 'multivariate'
                                                  : 'boolean'
                                        }
                                        onChange={(value) => {
                                            clearHighlight('flagType')
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
                                                optionally attach a JSON payload when the flag is{' '}
                                                <code className="text-xs">true</code>.
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

                                                        <LemonLabel info="Optionally specify a JSON payload to be returned when this variant is selected.">
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
                                        <LemonLabel info="Specify a JSON payload to be returned for this remote config flag.">
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
                                                            <code className="text-xs">getFeatureFlagPayload</code>.
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
                                        highlightedFields={highlightedFields}
                                        onClearHighlight={clearHighlight}
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
