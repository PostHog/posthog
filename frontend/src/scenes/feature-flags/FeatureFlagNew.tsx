import './FeatureFlag.scss'

import { useState } from 'react'

import { IconCode, IconGlobe, IconInfo, IconList, IconPlus, IconServer, IconToggle } from '@posthog/icons'
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

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import 'lib/lemon-ui/Lettermark'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FeatureFlagInstructions } from './FeatureFlagInstructions'

export function FeatureFlagNew(): JSX.Element {
    const [showInstructions, setShowInstructions] = useState(false)

    return (
        <>
            <SceneTitleSection
                name="my-feature-flag"
                resourceType={{
                    type: 'feature_flag',
                }}
                actions={
                    <>
                        <LemonButton data-attr="cancel-feature-flag" type="secondary" size="small" onClick={() => {}}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" data-attr="save-feature-flag" htmlType="submit" size="small">
                            Save
                        </LemonButton>
                    </>
                }
            />

            <SceneContent>
                <div className="flex gap-4 mt-4 flex-wrap">
                    <div className="flex-1 min-w-[20rem] flex flex-col gap-4">
                        <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                            <LemonLabel info="The key is used to identify the feature flag in the code. Must be unique.">
                                Flag key
                            </LemonLabel>
                            <LemonInput
                                placeholder="Enter a unique key - e.g. new-landing-page, betaFeature, ab_test_1"
                                value="my-feature-flag"
                            />

                            <LemonLabel>Description</LemonLabel>
                            <LemonTextArea placeholder="(Optional) A description of the feature flag for your reference." />

                            <LemonDivider />

                            <Tooltip
                                title="When enabled, this flag evaluates according to your release conditions. When disabled, this flag will not be evaluated and PostHog SDKs default to returning false."
                                placement="right"
                            >
                                <LemonSwitch
                                    label={
                                        <span className="flex items-center">
                                            <span>Enabled</span>
                                            <IconInfo className="ml-1 text-lg" />
                                        </span>
                                    }
                                    bordered
                                    fullWidth
                                    checked={true}
                                />
                            </Tooltip>
                            <Tooltip
                                title={
                                    <>
                                        If your feature flag is applied before identifying the user, use this to ensure
                                        that the flag value remains consistent for the same user. Depending on your
                                        setup, this option might not always be suitable. This feature requires creating
                                        profiles for anonymous users.{' '}
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
                                    bordered
                                    fullWidth
                                    label={
                                        <span className="flex items-center">
                                            <span>Persist flag across authentication steps</span>
                                            <IconInfo className="ml-1 text-lg" />
                                        </span>
                                    }
                                    checked={false}
                                />
                            </Tooltip>
                        </div>

                        <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                            <LemonLabel>Advanced options</LemonLabel>

                            <LemonSelect
                                fullWidth
                                options={[
                                    {
                                        label: (
                                            <div className="flex flex-col">
                                                <span className="font-medium"> Both client and server</span>
                                                <span className="text-xs text-muted">
                                                    Single-user apps + multi-user systems
                                                </span>
                                            </div>
                                        ),
                                        value: 'all',
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
                                        value: 'client',
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
                                        value: 'server',
                                        icon: <IconServer />,
                                    },
                                ]}
                                value="all"
                            />
                        </div>
                    </div>
                    <div className="flex-2 flex flex-col gap-4">
                        <div className="rounded border p-3 bg-white gap-4 flex flex-col">
                            <div className="flex flex-col gap-2">
                                <LemonLabel>Value</LemonLabel>
                                <LemonSelect
                                    fullWidth
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
                                                        Single payload with optional static payload
                                                    </span>
                                                </div>
                                            ),
                                            value: 'remote_config',
                                            icon: <IconCode />,
                                        },
                                    ]}
                                    value="multivariate"
                                />
                            </div>

                            <div className="flex flex-col gap-2">
                                <LemonLabel>Variants</LemonLabel>

                                <LemonCollapse
                                    panels={[
                                        {
                                            key: 'variant-1',
                                            header: (
                                                <>
                                                    <div className="flex gap-2 items-center">
                                                        <Lettermark
                                                            name="A"
                                                            color={LettermarkColor.Gray}
                                                            size="small"
                                                        />
                                                        <span className="text-sm font-medium">control</span>
                                                        <span className="text-xs text-muted">(50%)</span>
                                                    </div>
                                                </>
                                            ),
                                            content: (
                                                <div className="flex flex-col gap-2">
                                                    <LemonLabel>Variant key</LemonLabel>
                                                    <LemonInput placeholder="Enter a variant key - e.g. control, test, variant_1" />
                                                    <LemonLabel>Rollout percentage</LemonLabel>
                                                    <LemonInput placeholder="Enter a rollout percentage - e.g. 50" />
                                                    <LemonLabel>Description</LemonLabel>
                                                    <LemonTextArea placeholder="Enter a description for the variant" />
                                                </div>
                                            ),
                                        },
                                        {
                                            key: 'variant-2',
                                            header: (
                                                <>
                                                    <div className="flex gap-2 items-center">
                                                        <Lettermark
                                                            name="B"
                                                            color={LettermarkColor.Gray}
                                                            size="small"
                                                        />
                                                        <span className="text-sm font-medium">test</span>
                                                        <span className="text-xs text-muted">(50%)</span>
                                                    </div>
                                                </>
                                            ),
                                            content: (
                                                <div className="flex flex-col gap-2">
                                                    <LemonLabel>Variant key</LemonLabel>
                                                    <LemonInput placeholder="Enter a variant key - e.g. control, test, variant_1" />
                                                    <LemonLabel>Rollout percentage</LemonLabel>
                                                    <LemonInput placeholder="Enter a rollout percentage - e.g. 50" />
                                                    <LemonLabel>Description</LemonLabel>
                                                    <LemonTextArea placeholder="Enter a description for the variant" />
                                                </div>
                                            ),
                                        },
                                    ]}
                                />

                                <div>
                                    <LemonButton type="secondary" icon={<IconPlus />}>
                                        Add variant
                                    </LemonButton>
                                </div>
                            </div>
                        </div>

                        <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                            <LemonLabel>Release conditions</LemonLabel>
                            <p>
                                Specify users for flag release. Condition sets are evaluated top to bottom - the first
                                matching set is used. A condition matches when all property filters pass AND the target
                                falls within the rollout percentage.
                            </p>

                            <LemonSelect
                                options={[
                                    {
                                        value: 'user_id',
                                        label: (
                                            <div className="flex flex-col">
                                                <span className="font-medium">Match by user ID</span>
                                                <span className="text-xs text-muted">
                                                    Stable assignment for logged-in users based on their unique user ID.
                                                </span>
                                            </div>
                                        ),
                                    },
                                    {
                                        value: 'device_id',
                                        label: (
                                            <div className="flex flex-col">
                                                <span className="font-medium">Device ID</span>
                                                <span className="text-xs text-muted">
                                                    Stable assignment per device. Good fit for experiments on anonymous
                                                    users.
                                                </span>
                                            </div>
                                        ),
                                    },
                                    {
                                        value: 'group',
                                        label: (
                                            <div className="flex flex-col">
                                                <span className="font-medium">Group</span>
                                                <span className="text-xs text-muted">
                                                    Stable assignment for everyone in an organization, company, or other
                                                    custom group type.
                                                </span>
                                            </div>
                                        ),
                                    },
                                ]}
                                value="user_id"
                            />
                            <LemonCollapse
                                panels={[
                                    {
                                        key: 'condition-1',
                                        header: (
                                            <>
                                                <div className="flex gap-2 items-center flex-1">
                                                    <Lettermark name="1" color={LettermarkColor.Gray} size="small" />
                                                    <span className="text-sm font-medium mr-2">Condition 1</span>
                                                    <code className="text-xs text-muted rounded px-1 py-0.5">
                                                        email contains @posthog.com
                                                    </code>
                                                    <span className="flex-1" />
                                                    <span className="text-xs text-muted">(30%)</span>
                                                </div>
                                            </>
                                        ),
                                        content: (
                                            <div className="flex flex-col gap-2">
                                                <LemonLabel>Match filters</LemonLabel>
                                                <LemonButton type="secondary" icon={<IconPlus />}>
                                                    Add filter
                                                </LemonButton>
                                                <LemonLabel>Rollout percentage</LemonLabel>
                                                <div className="flex items-center gap-2">
                                                    <LemonSlider
                                                        className="flex-1"
                                                        value={30}
                                                        min={0}
                                                        max={100}
                                                        step={1}
                                                    />
                                                    <LemonInput
                                                        type="number"
                                                        placeholder="Enter a rollout percentage - e.g. 30"
                                                        value={30}
                                                        className="w-20"
                                                    />
                                                </div>
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        </div>

                        {showInstructions ? (
                            <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                                <LemonButton
                                    className="-m-2"
                                    icon={<IconCode />}
                                    onClick={() => setShowInstructions(false)}
                                >
                                    Implementation
                                </LemonButton>
                                <LemonDivider />
                                <FeatureFlagInstructions
                                    featureFlag={
                                        {
                                            key: 'feature-flag-1',
                                            filters: {},
                                        } as any
                                    }
                                />
                            </div>
                        ) : (
                            <div className="rounded border bg-surface-secondary gap-2 flex flex-col p-3">
                                <LemonButton
                                    className="-m-2"
                                    icon={<IconCode />}
                                    onClick={() => setShowInstructions(true)}
                                >
                                    Show implementation
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
            </SceneContent>
        </>
    )
}
