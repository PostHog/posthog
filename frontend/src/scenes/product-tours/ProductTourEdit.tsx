import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EditInToolbarButton } from './components/EditInToolbarButton'
import { productTourLogic } from './productTourLogic'

export function ProductTourEdit({ id }: { id: string }): JSX.Element {
    const { productTour, productTourLoading, productTourForm, targetingFlagFilters, isProductTourFormSubmitting } =
        useValues(productTourLogic({ id }))
    const { editingProductTour, setProductTourFormValue, submitProductTourForm } = useActions(productTourLogic({ id }))

    if (!productTour) {
        return <LemonSkeleton />
    }

    const conditions = productTourForm.content?.conditions || {}

    return (
        <Form logic={productTourLogic} props={{ id }} formKey="productTourForm">
            <SceneContent>
                <SceneTitleSection
                    name={productTour.name}
                    description="Edit product tour settings"
                    resourceType={{ type: 'product_tour' }}
                    isLoading={productTourLoading}
                    actions={
                        <>
                            <EditInToolbarButton tourId={id} />
                            <LemonButton type="secondary" size="small" onClick={() => editingProductTour(false)}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => submitProductTourForm()}
                                loading={isProductTourFormSubmitting}
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                />

                <div className="space-y-6 max-w-3xl">
                    <LemonField name="name" label="Name">
                        <LemonInput
                            placeholder="Tour name"
                            value={productTourForm.name}
                            onChange={(value) => setProductTourFormValue('name', value)}
                        />
                    </LemonField>

                    <LemonField name="description" label="Description">
                        <LemonInput
                            placeholder="Optional description"
                            value={productTourForm.description}
                            onChange={(value) => setProductTourFormValue('description', value)}
                        />
                    </LemonField>

                    <LemonDivider />

                    <div>
                        <h3 className="font-semibold mb-2">Tour URLs</h3>
                        <p className="text-secondary text-sm mb-4">
                            Tour will only display on URLs matching these conditions
                        </p>
                        <div className="flex gap-2">
                            <LemonSelect
                                value={conditions.urlMatchType || 'contains'}
                                onChange={(value) => {
                                    setProductTourFormValue('content', {
                                        ...productTourForm.content,
                                        conditions: {
                                            ...conditions,
                                            urlMatchType: value,
                                        },
                                    })
                                }}
                                options={[
                                    { label: 'Contains', value: 'contains' },
                                    { label: 'Exact match', value: 'exact' },
                                    { label: 'Regex', value: 'regex' },
                                ]}
                            />
                            <LemonInput
                                className="flex-1"
                                value={conditions.url || ''}
                                onChange={(value) => {
                                    setProductTourFormValue('content', {
                                        ...productTourForm.content,
                                        conditions: {
                                            ...conditions,
                                            url: value,
                                        },
                                    })
                                }}
                                placeholder="e.g. /dashboard or https://example.com/app"
                            />
                        </div>
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="font-semibold mb-2">Display conditions</h3>
                        <p className="text-secondary text-sm mb-4">
                            Configure how and when this tour is shown to users.
                        </p>

                        <div className="space-y-4">
                            <div className="border rounded p-4 bg-surface-primary">
                                <div className="flex items-center justify-between mb-2">
                                    <h4 className="font-semibold">Auto-show this tour</h4>
                                    <LemonSwitch
                                        checked={productTourForm.auto_launch}
                                        onChange={(checked) => setProductTourFormValue('auto_launch', checked)}
                                    />
                                </div>
                                <p className="text-secondary text-sm">
                                    Automatically show to users who match the targeting conditions.
                                </p>

                                {productTourForm.auto_launch && (
                                    <div className="mt-4 pt-4 border-t space-y-4">
                                        <div>
                                            <h5 className="font-semibold mb-2">User targeting</h5>
                                            <p className="text-secondary text-sm mb-4">
                                                Target specific users based on their properties. Users who have
                                                completed or dismissed this tour are automatically excluded.
                                            </p>
                                            <BindLogic
                                                logic={featureFlagLogic}
                                                props={{
                                                    id: productTour.internal_targeting_flag?.id
                                                        ? String(productTour.internal_targeting_flag.id)
                                                        : 'new',
                                                }}
                                            >
                                                <FeatureFlagReleaseConditions
                                                    id={
                                                        productTour.internal_targeting_flag?.id
                                                            ? String(productTour.internal_targeting_flag.id)
                                                            : 'new'
                                                    }
                                                    excludeTitle={true}
                                                    filters={
                                                        targetingFlagFilters || {
                                                            groups: [
                                                                {
                                                                    variant: '',
                                                                    rollout_percentage: 100,
                                                                    properties: [],
                                                                },
                                                            ],
                                                        }
                                                    }
                                                    onChange={(filters) => {
                                                        setProductTourFormValue('targeting_flag_filters', filters)
                                                    }}
                                                />
                                            </BindLogic>
                                        </div>

                                        {productTour.internal_targeting_flag && (
                                            <>
                                                <LemonDivider />
                                                <div>
                                                    <h5 className="font-semibold mb-2">Feature flag</h5>
                                                    <p className="text-secondary text-sm mb-4">
                                                        This tour uses an internal feature flag for targeting.
                                                    </p>
                                                    <div className="flex items-center gap-2">
                                                        <LemonTag>{productTour.feature_flag_key}</LemonTag>
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>

                            <div className="border rounded p-4 bg-surface-primary">
                                <h4 className="font-semibold mb-2">Trigger selector</h4>
                                <p className="text-secondary text-sm mb-4">
                                    Show this tour when users click an element matching this CSS selector.
                                </p>
                                <LemonInput
                                    className="font-mono"
                                    value={conditions.selector || ''}
                                    onChange={(value) => {
                                        setProductTourFormValue('content', {
                                            ...productTourForm.content,
                                            conditions: {
                                                ...conditions,
                                                selector: value,
                                            },
                                        })
                                    }}
                                    placeholder="e.g. #help-button or .tour-trigger"
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </SceneContent>
        </Form>
    )
}
