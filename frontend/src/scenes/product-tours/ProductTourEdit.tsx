import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
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
    const { editingProductTour, setProductTourFormValue, submitProductTourForm, setFlagPropertyErrors } = useActions(
        productTourLogic({ id })
    )

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
                        <h3 className="font-semibold mb-2">Tour content</h3>
                        <p className="text-secondary text-sm mb-4">
                            Tour steps and appearance can only be edited in the toolbar.
                        </p>
                        <EditInToolbarButton tourId={id} />
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="font-semibold mb-2">URL targeting</h3>
                        <p className="text-secondary text-sm mb-4">
                            Only show this tour on pages matching this URL pattern.
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
                                placeholder="e.g., /dashboard or https://example.com/app"
                            />
                        </div>
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="font-semibold mb-2">User targeting</h3>
                        <p className="text-secondary text-sm mb-4">
                            Target specific users based on their properties. Users who have completed or dismissed this
                            tour are automatically excluded.
                        </p>
                        <BindLogic
                            logic={featureFlagLogic}
                            props={{ id: String(productTour.internal_targeting_flag?.id) || 'new' }}
                        >
                            <LemonField.Pure label="Person properties">
                                {!targetingFlagFilters && (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            setProductTourFormValue('targeting_flag_filters', {
                                                groups: [
                                                    {
                                                        variant: '',
                                                        rollout_percentage: 100,
                                                        properties: [],
                                                    },
                                                ],
                                            })
                                        }}
                                    >
                                        Add property targeting
                                    </LemonButton>
                                )}
                                {targetingFlagFilters && (
                                    <>
                                        <div className="mt-2">
                                            <FeatureFlagReleaseConditions
                                                id={String(productTour.internal_targeting_flag?.id) || 'new'}
                                                excludeTitle={true}
                                                filters={targetingFlagFilters}
                                                onChange={(filters, errors) => {
                                                    setFlagPropertyErrors(errors)
                                                    setProductTourFormValue('targeting_flag_filters', filters)
                                                }}
                                                showTrashIconWithOneCondition
                                                removedLastConditionCallback={() => {
                                                    setProductTourFormValue('targeting_flag_filters', null)
                                                }}
                                            />
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            status="danger"
                                            className="w-max mt-2"
                                            onClick={() => {
                                                setProductTourFormValue('targeting_flag_filters', null)
                                            }}
                                        >
                                            Remove all property targeting
                                        </LemonButton>
                                    </>
                                )}
                            </LemonField.Pure>
                        </BindLogic>
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="font-semibold mb-2">Feature flag</h3>
                        <p className="text-secondary text-sm mb-4">
                            This tour uses an internal feature flag for targeting. The flag is automatically created and
                            managed.
                        </p>
                        {productTour.internal_targeting_flag ? (
                            <div className="flex items-center gap-2">
                                <LemonTag>{productTour.feature_flag_key}</LemonTag>
                            </div>
                        ) : (
                            <span className="text-secondary text-sm">No feature flag configured.</span>
                        )}
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="font-semibold mb-2">Authorized domains</h3>
                        <p className="text-secondary text-sm mb-4">
                            The toolbar can only be launched on authorized domains.
                        </p>
                        <AuthorizedUrlList
                            type={AuthorizedUrlListType.TOOLBAR_URLS}
                            addText="Add authorized URL"
                            showLaunch={false}
                        />
                    </div>
                </div>
            </SceneContent>
        </Form>
    )
}
