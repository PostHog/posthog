import './Experiment.scss'

import { IconMagicWand, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonDivider, LemonInput, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { ExperimentVariantNumber } from 'lib/components/SeriesGlyph'
import { FEATURE_FLAGS, MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { capitalizeFirstLetter } from 'lib/utils'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'

import { experimentLogic } from './experimentLogic'

const ExperimentFormFields = (): JSX.Element => {
    const { experiment, featureFlags, groupTypes, aggregationLabel } = useValues(experimentLogic)
    const {
        addExperimentGroup,
        removeExperimentGroup,
        setExperiment,
        setNewExperimentInsight,
        createExperiment,
        setExperimentType,
        setExperimentValue,
    } = useActions(experimentLogic)
    const { webExperimentsAvailable } = useValues(experimentsLogic)

    return (
        <div>
            <div className="space-y-8">
                <div className="space-y-6 max-w-120">
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Pricing page conversion" data-attr="experiment-name" />
                    </LemonField>
                    <div className="flex items-center">
                        <LemonField
                            name="feature_flag_key"
                            label="Feature flag key"
                            help="Each experiment is backed by a feature flag. You'll use this key in your code."
                        >
                            <div className="flex items-center space-x-2">
                                <LemonInput
                                    className="flex-grow"
                                    placeholder="pricing-page-conversion"
                                    data-attr="experiment-feature-flag-key"
                                />
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    title="Generate key"
                                    disabledReason={!experiment.name ? 'Please enter an experiment name' : undefined}
                                    onClick={() => {
                                        const feature_flag_key = experiment.name
                                            .toLowerCase()
                                            .replace(/[^A-Za-z0-9-_]+/g, '-')
                                        // setExperiment({
                                        //     feature_flag_key
                                        // })
                                        setExperimentValue('feature_flag_key', feature_flag_key)
                                    }}
                                >
                                    <IconMagicWand />
                                </LemonButton>
                            </div>
                        </LemonField>
                    </div>
                    <LemonField name="description" label="Description">
                        <LemonTextArea
                            placeholder="The goal of this experiment is ..."
                            data-attr="experiment-description"
                        />
                    </LemonField>
                </div>
                {webExperimentsAvailable && (
                    <div className="mt-10">
                        <h3 className="mb-1">Experiment type</h3>
                        <div className="text-xs text-muted font-medium tracking-normal">
                            Select your experiment setup, this cannot be changed once saved.
                        </div>
                        <LemonDivider />
                        <LemonRadio
                            value={experiment.type}
                            className="space-y-2 -mt-2"
                            onChange={(type) => {
                                setExperimentType(type)
                            }}
                            options={[
                                {
                                    value: 'product',
                                    label: (
                                        <div className="translate-y-2">
                                            <div>Product experiment</div>
                                            <div className="text-xs text-muted">
                                                Use custom code to manage how variants modify your product.
                                            </div>
                                        </div>
                                    ),
                                },
                                {
                                    value: 'web',
                                    label: (
                                        <div className="translate-y-2">
                                            <div>No-code web experiment</div>
                                            <div className="text-xs text-muted">
                                                Define variants on your website using the PostHog toolbar, no coding
                                                required.
                                            </div>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </div>
                )}
                <div>
                    <h3 className="mt-10">Participant type</h3>
                    <div className="text-xs text-muted">
                        The type on which to aggregate metrics. You can change this at any time during the experiment.
                    </div>
                    <LemonDivider />
                    <LemonRadio
                        value={
                            experiment.parameters.aggregation_group_type_index != undefined
                                ? experiment.parameters.aggregation_group_type_index
                                : -1
                        }
                        onChange={(rawGroupTypeIndex) => {
                            const groupTypeIndex = rawGroupTypeIndex !== -1 ? rawGroupTypeIndex : undefined

                            setExperiment({
                                parameters: {
                                    ...experiment.parameters,
                                    aggregation_group_type_index: groupTypeIndex ?? undefined,
                                },
                            })
                            setNewExperimentInsight()
                        }}
                        options={[
                            { value: -1, label: 'Persons' },
                            ...Array.from(groupTypes.values()).map((groupType) => ({
                                value: groupType.group_type_index,
                                label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                            })),
                        ]}
                    />
                </div>
                <div className="mt-10">
                    <h3 className="mb-1">Variants</h3>
                    <div className="text-xs text-muted">Add up to 9 variants to test against your control.</div>
                    <LemonDivider />
                    <div className="grid grid-cols-2 gap-4 max-w-160">
                        <div className="max-w-60">
                            <h3>Control</h3>
                            <div className="flex items-center">
                                <Group key={0} name={['parameters', 'feature_flag_variants', 0]}>
                                    <ExperimentVariantNumber index={0} className="h-7 w-7 text-base" />
                                    <LemonField name="key" className="ml-2 flex-grow">
                                        <LemonInput
                                            disabled
                                            data-attr="experiment-variant-key"
                                            data-key-index={0}
                                            className="ph-ignore-input"
                                            fullWidth
                                            autoComplete="off"
                                            autoCapitalize="off"
                                            autoCorrect="off"
                                            spellCheck={false}
                                        />
                                    </LemonField>
                                </Group>
                            </div>
                            <div className="text-muted text-xs mt-2">
                                Included automatically, cannot be edited or removed
                            </div>
                        </div>
                        <div className="max-w-100">
                            <h3>Test(s)</h3>
                            {experiment.parameters.feature_flag_variants?.map((_, index) => {
                                if (index === 0) {
                                    return null
                                }

                                return (
                                    <Group key={index} name={['parameters', 'feature_flag_variants', index]}>
                                        <div
                                            key={`variant-${index}`}
                                            className={`flex items-center space-x-2 ${index > 1 && 'mt-2'}`}
                                        >
                                            <ExperimentVariantNumber index={index} className="h-7 w-7 text-base" />
                                            <LemonField name="key" className="flex-grow">
                                                <LemonInput
                                                    data-attr="experiment-variant-key"
                                                    data-key-index={index.toString()}
                                                    className="ph-ignore-input"
                                                    fullWidth
                                                    autoComplete="off"
                                                    autoCapitalize="off"
                                                    autoCorrect="off"
                                                    spellCheck={false}
                                                />
                                            </LemonField>
                                            <div className={`${index === 1 && 'pr-9'}`}>
                                                {index !== 1 && (
                                                    <Tooltip title="Delete this variant" placement="top-start">
                                                        <LemonButton
                                                            size="small"
                                                            icon={<IconTrash />}
                                                            onClick={() => removeExperimentGroup(index)}
                                                        />
                                                    </Tooltip>
                                                )}
                                            </div>
                                        </div>
                                    </Group>
                                )
                            })}
                            <div className="text-muted text-xs ml-9 mr-20 mt-2">
                                Alphanumeric, hyphens and underscores only
                            </div>
                            {(experiment.parameters.feature_flag_variants.length ?? 0) < MAX_EXPERIMENT_VARIANTS && (
                                <LemonButton
                                    className="ml-9 mt-2"
                                    type="secondary"
                                    onClick={() => addExperimentGroup()}
                                    icon={<IconPlusSmall />}
                                    data-attr="add-test-variant"
                                >
                                    Add test variant
                                </LemonButton>
                            )}
                        </div>
                    </div>
                </div>
                {featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOLDOUTS] && (
                    <div>
                        <h3>Holdout group</h3>
                        <div className="text-xs text-muted">Exclude a stable group of users from the experiment.</div>
                        <LemonDivider />
                        <HoldoutSelector />
                    </div>
                )}
            </div>
            <LemonButton
                className="mt-2"
                type="primary"
                data-attr="save-experiment"
                onClick={() => createExperiment(true)}
            >
                Save as draft
            </LemonButton>
        </div>
    )
}

export const HoldoutSelector = (): JSX.Element => {
    const { experiment, holdouts } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)

    const holdoutOptions = holdouts.map((holdout) => ({
        value: holdout.id,
        label: holdout.name,
    }))
    holdoutOptions.unshift({ value: null, label: 'No holdout' })

    return (
        <div className="mt-4 mb-8">
            <LemonSelect
                options={holdoutOptions}
                value={experiment.holdout_id || null}
                onChange={(value) => {
                    setExperiment({
                        ...experiment,
                        holdout_id: value,
                    })
                }}
                data-attr="experiment-holdout-selector"
            />
        </div>
    )
}

export function ExperimentForm(): JSX.Element {
    const { props } = useValues(experimentLogic)

    return (
        <div>
            <Form
                id="experiment-step"
                logic={experimentLogic}
                formKey="experiment"
                props={props}
                enableFormOnSubmit
                className="space-y-6 experiment-form"
            >
                <ExperimentFormFields />
            </Form>
        </div>
    )
}
