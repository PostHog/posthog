import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { featureFlagLogic as featureFlagSceneLogic } from 'scenes/feature-flags/featureFlagLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductTourStep } from '~/types'

import { AnnouncementContentEditor } from './AnnouncementContentEditor'
import { AutoShowSection } from './components/AutoShowSection'
import { EditInToolbarButton } from './components/EditInToolbarButton'
import { ProductTourCustomization } from './components/ProductTourCustomization'
import { ProductTourStepsEditor } from './editor'
import { ProductTourEditTab, productTourLogic } from './productTourLogic'
import { isAnnouncement } from './productToursLogic'

export function ProductTourEdit({ id }: { id: string }): JSX.Element {
    const {
        productTour,
        productTourLoading,
        productTourForm,
        targetingFlagFilters,
        isProductTourFormSubmitting,
        editTab,
    } = useValues(productTourLogic({ id }))
    const { editingProductTour, setProductTourFormValue, submitProductTourForm, setEditTab } = useActions(
        productTourLogic({ id })
    )

    const { featureFlags } = useValues(featureFlagLogic)
    const showStepsEditor = featureFlags[FEATURE_FLAGS.PRODUCT_TOURS_RICH_TEXT]

    if (!productTour) {
        return <LemonSkeleton />
    }

    const conditions = productTourForm.content?.conditions || {}

    return (
        <Form logic={productTourLogic} props={{ id }} formKey="productTourForm">
            <SceneContent>
                <SceneTitleSection
                    name={productTour.name}
                    description={isAnnouncement(productTour) ? 'Edit announcement' : 'Edit product tour settings'}
                    resourceType={{ type: 'product_tour' }}
                    isLoading={productTourLoading}
                    actions={
                        <>
                            {!isAnnouncement(productTour) && <EditInToolbarButton tourId={id} />}
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

                <LemonTabs
                    activeKey={editTab}
                    onChange={(newTab) => setEditTab(newTab as ProductTourEditTab)}
                    tabs={[
                        { key: ProductTourEditTab.Configuration, label: 'Configuration' },
                        ...(showStepsEditor
                            ? [
                                  {
                                      key: ProductTourEditTab.Steps,
                                      label: isAnnouncement(productTour) ? 'Content' : 'Steps',
                                  },
                              ]
                            : []),
                        { key: ProductTourEditTab.Customization, label: 'Customization' },
                    ]}
                />

                {editTab === ProductTourEditTab.Configuration && (
                    <div className="space-y-6 max-w-3xl">
                        <LemonField name="name" label="Name">
                            <LemonInput
                                placeholder="Tour name"
                                value={productTourForm.name}
                                onChange={(value) => setProductTourFormValue('name', value)}
                            />
                        </LemonField>

                        <LemonDivider />

                        <div>
                            <h3 className="font-semibold mb-2">Display conditions</h3>
                            <p className="text-secondary text-sm mb-4">
                                Configure how and when this tour is shown to users.
                            </p>

                            <div className="space-y-4">
                                <div className="border rounded p-4 bg-surface-primary">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h4 className="font-semibold">Auto-show this tour</h4>
                                            <p className="text-secondary text-sm mb-0">
                                                Automatically show this tour to users who match your conditions
                                            </p>
                                        </div>
                                        <LemonSwitch
                                            checked={productTourForm.auto_launch}
                                            onChange={(checked) => setProductTourFormValue('auto_launch', checked)}
                                        />
                                    </div>

                                    {productTourForm.auto_launch && (
                                        <div className="mt-4 pt-4 border-t space-y-4">
                                            <div>
                                                <h5 className="font-semibold mb-3">
                                                    Who to show&nbsp;
                                                    <Tooltip title="Only auto-show the tour to users who match these conditions">
                                                        <IconInfo />
                                                    </Tooltip>
                                                </h5>
                                                <BindLogic
                                                    logic={featureFlagSceneLogic}
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

                                            <AutoShowSection
                                                conditions={conditions}
                                                onChange={(newConditions) => {
                                                    setProductTourFormValue('content', {
                                                        ...productTourForm.content,
                                                        conditions: newConditions,
                                                    })
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>

                                <div className="border rounded p-4 bg-surface-primary">
                                    <h4 className="font-semibold mb-2">Manual trigger</h4>
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
                )}

                {editTab === ProductTourEditTab.Steps &&
                    (isAnnouncement(productTour) ? (
                        <AnnouncementContentEditor
                            step={productTourForm.content?.steps?.[0]}
                            appearance={productTourForm.content?.appearance}
                            onChange={(step: ProductTourStep) => {
                                setProductTourFormValue('content', {
                                    ...productTourForm.content,
                                    steps: [step],
                                })
                            }}
                        />
                    ) : (
                        <ProductTourStepsEditor
                            steps={productTourForm.content?.steps ?? []}
                            appearance={productTourForm.content?.appearance}
                            onChange={(steps: ProductTourStep[]) => {
                                setProductTourFormValue('content', {
                                    ...productTourForm.content,
                                    steps,
                                })
                            }}
                        />
                    ))}

                {editTab === ProductTourEditTab.Customization && (
                    <ProductTourCustomization
                        appearance={productTourForm.content?.appearance}
                        steps={productTourForm.content?.steps ?? []}
                        onChange={(appearance) => {
                            setProductTourFormValue('content', {
                                ...productTourForm.content,
                                appearance,
                            })
                        }}
                    />
                )}
            </SceneContent>
        </Form>
    )
}
