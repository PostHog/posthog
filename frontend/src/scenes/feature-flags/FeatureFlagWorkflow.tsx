import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { router } from 'kea-router'
import { useState } from 'react'

import {
    IconBalance,
    IconCode,
    IconGlobe,
    IconInfo,
    IconList,
    IconPlus,
    IconServer,
    IconToggle,
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
    Tooltip,
} from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import { FeatureFlagTemplates } from './FeatureFlagTemplates'
import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'

export function FeatureFlagWorkflow({ id }: FeatureFlagLogicProps): JSX.Element {
    const { props, featureFlag, multivariateEnabled, variants, variantErrors, isEditingFlag } =
        useValues(featureFlagLogic)
    const {
        setMultivariateEnabled,
        setFeatureFlag,
        addVariant,
        removeVariant,
        distributeVariantsEqually,
        setFeatureFlagFilters,
        editFeatureFlag,
        loadFeatureFlag,
    } = useActions(featureFlagLogic)
    const { tags: availableTags } = useValues(tagsModel)
    const hasEvaluationTags = useFeatureFlag('FLAG_EVALUATION_TAGS')

    const [showImplementation, setShowImplementation] = useState(false)
    const [openVariants, setOpenVariants] = useState<string[]>([])

    const isNewFeatureFlag = id === 'new' || id === undefined

    const updateVariant = (
        index: number,
        field: 'key' | 'name' | 'rollout_percentage',
        value: string | number
    ): void => {
        const currentVariants = [...variants]
        currentVariants[index] = { ...currentVariants[index], [field]: value }
        setFeatureFlag({
            ...featureFlag,
            filters: {
                ...featureFlag?.filters,
                multivariate: {
                    ...featureFlag?.filters?.multivariate,
                    variants: currentVariants,
                },
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
        return <div>Loading...</div>
    }

    // Read-only view when not editing an existing flag
    if (!isNewFeatureFlag && !isEditingFlag) {
        return (
            <>
                <SceneTitleSection
                    name={featureFlag.key}
                    resourceType={{
                        type: featureFlag.active ? 'feature_flag' : 'feature_flag_off',
                    }}
                    actions={
                        <LemonButton
                            type="primary"
                            data-attr="edit-feature-flag"
                            size="small"
                            onClick={() => editFeatureFlag(true)}
                        >
                            Edit
                        </LemonButton>
                    }
                />
                <SceneContent>
                    <div className="flex flex-col gap-4">
                        {/* Summary card */}
                        <div className="rounded border p-4 bg-bg-light">
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <LemonLabel>Flag key</LemonLabel>
                                    <div className="font-mono text-sm">{featureFlag.key}</div>
                                </div>
                                <div>
                                    <LemonLabel>Status</LemonLabel>
                                    <div className={featureFlag.active ? 'text-success' : 'text-muted'}>
                                        {featureFlag.active ? 'Enabled' : 'Disabled'}
                                    </div>
                                </div>
                                {featureFlag.name && (
                                    <div className="col-span-2">
                                        <LemonLabel>Description</LemonLabel>
                                        <div className="text-sm">{featureFlag.name}</div>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Release conditions - read only */}
                        {!featureFlag.is_remote_configuration && (
                            <div className="rounded border p-4 bg-bg-light">
                                <FeatureFlagReleaseConditions
                                    id={String(props.id)}
                                    filters={featureFlag.filters}
                                    readOnly
                                />
                            </div>
                        )}

                        {/* Implementation */}
                        <div className="rounded border p-4 bg-bg-light">
                            <FeatureFlagCodeExample featureFlag={featureFlag} />
                        </div>
                    </div>
                </SceneContent>
            </>
        )
    }

    // Edit mode
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
                    <div className="flex gap-4 mt-4 flex-wrap">
                        {/* Left column - narrow */}
                        <div className="flex-1 min-w-[20rem] flex flex-col gap-4">
                            {/* Main settings card */}
                            <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
                                <LemonField
                                    name="key"
                                    label="Flag key"
                                    info="The key is used to identify the feature flag in the code. Must be unique."
                                >
                                    <LemonInput
                                        data-attr="feature-flag-key"
                                        className="ph-ignore-input"
                                        autoComplete="off"
                                        autoCapitalize="off"
                                        autoCorrect="off"
                                        spellCheck={false}
                                        placeholder="Enter a unique key - e.g. new-landing-page, betaFeature, ab_test_1"
                                    />
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
                                            placement="right"
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

                                <LemonField name="ensure_experience_continuity">
                                    {({ value, onChange }) => (
                                        <Tooltip
                                            title={
                                                <>
                                                    If your feature flag is applied before identifying the user, use
                                                    this to ensure that the flag value remains consistent for the same
                                                    user. Depending on your setup, this option might not always be
                                                    suitable. This feature requires creating profiles for anonymous
                                                    users.{' '}
                                                    <Link
                                                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                                                        target="_blank"
                                                    >
                                                        Learn more
                                                    </Link>
                                                </>
                                            }
                                            placement="right"
                                        >
                                            <LemonSwitch
                                                checked={value}
                                                onChange={onChange}
                                                bordered
                                                fullWidth
                                                label={
                                                    <span className="flex items-center">
                                                        <span>Persist flag across authentication steps</span>
                                                        <IconInfo className="ml-1 text-lg" />
                                                    </span>
                                                }
                                                data-attr="feature-flag-persist-across-auth"
                                            />
                                        </Tooltip>
                                    )}
                                </LemonField>
                            </div>

                            {/* Advanced options card */}
                            <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
                                <LemonLabel>Advanced options</LemonLabel>

                                <LemonField name="evaluation_runtime">
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
                            </div>

                            {/* Tags & Evaluation Contexts card */}
                            <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
                                <LemonLabel
                                    info={
                                        hasEvaluationTags
                                            ? 'Use tags to organize flags. Mark tags as evaluation contexts to control when flags evaluate – flags only evaluate when the SDK provides matching environment tags.'
                                            : 'Use tags to organize and filter your feature flags.'
                                    }
                                >
                                    Tags & evaluation contexts
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
                                                tagsAvailable={availableTags.filter(
                                                    (tag: string) => !formTags?.includes(tag)
                                                )}
                                            />
                                        )}
                                    </LemonField>
                                )}
                            </div>
                        </div>

                        {/* Right column - wide */}
                        <div className="flex-2 flex flex-col gap-4" style={{ minWidth: '30rem' }}>
                            {/* Flag type card */}
                            <div className="rounded border p-3 bg-bg-light gap-4 flex flex-col">
                                <div className="flex flex-col gap-2">
                                    <LemonLabel>Flag type</LemonLabel>
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
                                                setMultivariateEnabled(false)
                                            } else if (value === 'multivariate') {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: false,
                                                })
                                                setMultivariateEnabled(true)
                                            } else {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: false,
                                                })
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
                                                icon: <IconToggle />,
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
                                            >
                                                Distribute equally
                                            </LemonButton>
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
                                                            name={alphabet[index]}
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

                                                        {/* Show effective percentage if there are release conditions with rollout */}
                                                        {(() => {
                                                            const groups = featureFlag?.filters?.groups || []
                                                            const releaseConditionsWithRollout = groups.filter(
                                                                (group) =>
                                                                    !group.variant &&
                                                                    (group.rollout_percentage ?? 100) < 100
                                                            )

                                                            if (releaseConditionsWithRollout.length > 0) {
                                                                const minRollout = Math.min(
                                                                    ...releaseConditionsWithRollout.map(
                                                                        (g) => g.rollout_percentage ?? 100
                                                                    )
                                                                )
                                                                const variantRollout = variant.rollout_percentage || 0
                                                                const effectiveRollout =
                                                                    (minRollout * variantRollout) / 100

                                                                return (
                                                                    <div className="text-xs mt-1 text-secondary">
                                                                        Effective: ~{effectiveRollout.toFixed(1)}% of
                                                                        all users
                                                                        <div className="text-muted">
                                                                            ({variantRollout}% of {minRollout}% eligible
                                                                            users)
                                                                        </div>
                                                                    </div>
                                                                )
                                                            }
                                                            return null
                                                        })()}

                                                        <LemonLabel>Description</LemonLabel>
                                                        <LemonTextArea
                                                            placeholder="Enter a description for the variant"
                                                            value={variant.name || ''}
                                                            onChange={(value) => updateVariant(index, 'name', value)}
                                                            data-attr={`feature-flag-variant-description-${index}`}
                                                        />

                                                        <LemonLabel>Payload</LemonLabel>
                                                        <JSONEditorInput
                                                            onChange={(value) => updateVariantPayload(index, value)}
                                                            value={featureFlag.filters?.payloads?.[variant.key]}
                                                            placeholder='{"key": "value"}'
                                                        />

                                                        {variants.length > 1 && (
                                                            <LemonButton
                                                                type="secondary"
                                                                status="danger"
                                                                size="small"
                                                                icon={<IconTrash />}
                                                                onClick={() => removeVariant(index)}
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
                                {!multivariateEnabled && (
                                    <div className="flex flex-col gap-2">
                                        <LemonLabel
                                            info={
                                                featureFlag.is_remote_configuration
                                                    ? 'Specify a JSON payload to be returned for this remote config flag.'
                                                    : 'Optionally specify a JSON payload to be returned when the flag evaluates to true.'
                                            }
                                        >
                                            Payload
                                        </LemonLabel>
                                        <div className="text-secondary text-xs mb-1">
                                            {featureFlag.is_remote_configuration ? (
                                                <>
                                                    Remote config flags always return the payload. Access it via{' '}
                                                    <code className="text-xs">getFeatureFlagPayload</code>.
                                                </>
                                            ) : (
                                                <>
                                                    When the flag evaluates to <code className="text-xs">true</code>,
                                                    this payload will be available via{' '}
                                                    <code className="text-xs">getFeatureFlagPayload</code>.
                                                </>
                                            )}
                                        </div>
                                        <Group name={['filters', 'payloads']}>
                                            <LemonField name="true">
                                                <JSONEditorInput placeholder='Examples: "A string", 2500, {"key": "value"}' />
                                            </LemonField>
                                        </Group>
                                    </div>
                                )}
                            </div>

                            {/* Release conditions card - skip for remote config */}
                            {!featureFlag.is_remote_configuration && (
                                <div className="rounded border p-3 bg-bg-light">
                                    <FeatureFlagReleaseConditionsCollapsible
                                        id={String(props.id)}
                                        filters={featureFlag.filters}
                                        onChange={setFeatureFlagFilters}
                                    />
                                </div>
                            )}

                            {/* Implementation section */}
                            {showImplementation ? (
                                <div className="rounded border p-3 bg-bg-light gap-2 flex flex-col">
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
                                <div className="rounded border bg-bg-light gap-2 flex flex-col p-3">
                                    <LemonButton
                                        className="-m-2"
                                        icon={<IconCode />}
                                        onClick={() => setShowImplementation(true)}
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
