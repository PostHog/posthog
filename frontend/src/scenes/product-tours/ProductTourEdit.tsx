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
import { BannerContentEditor } from './BannerContentEditor'
import { AutoShowSection } from './components/AutoShowSection'
import { BannerCustomization } from './components/BannerCustomization'
import { ProductTourCustomization } from './components/ProductTourCustomization'
import { ProductToursToolbarButton } from './components/ProductToursToolbarButton'
import { ProductTourStepsEditor } from './editor'
import { ProductTourEditTab, productTourLogic } from './productTourLogic'
import { isAnnouncement, isBannerAnnouncement } from './productToursLogic'

export function ProductTourEdit({ id }: { id: string }): JSX.Element {
    const {
        productTour,
        productTourLoading,
        productTourForm,
        productTourFormAllErrors,
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
    const entityKeyword = isAnnouncement(productTour) ? 'announcement' : 'tour'

    return (
        <Form logic={productTourLogic} props={{ id }} formKey="productTourForm">
            <SceneContent>
                <SceneTitleSection
                    name={productTour.name}
                    description={`Edit ${entityKeyword} settings`}
                    resourceType={{ type: 'product_tour' }}
                    isLoading={productTourLoading}
                    actions={
                        <>
                            <ProductToursToolbarButton
                                tourId={id}
                                mode={isAnnouncement(productTour) ? 'preview' : 'edit'}
                            />
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
                                Configure how and when this {entityKeyword} is shown to users.
                            </p>

                            <div className="space-y-4">
                                <div className="border rounded p-4 bg-surface-primary">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h4 className="font-semibold">Auto-show this tour</h4>
                                            <p className="text-secondary text-sm mb-0">
                                                Automatically show this {entityKeyword} to users who match your
                                                conditions
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
                                                    <Tooltip
                                                        title={`Only auto-show the ${entityKeyword} to users who match these conditions`}
                                                    >
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
                                        Show this {entityKeyword} when users click an element matching this CSS
                                        selector.
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
                        <>
                            {productTourFormAllErrors._form && (
                                <LemonField name="_form" className="mb-4">
                                    <span />
                                </LemonField>
                            )}
                            {isBannerAnnouncement(productTour) ? (
                                <BannerContentEditor
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
                            )}
                        </>
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

                {editTab === ProductTourEditTab.Customization &&
                    (isBannerAnnouncement(productTour) ? (
                        <BannerCustomization
                            appearance={productTourForm.content?.appearance}
                            step={productTourForm.content?.steps?.[0]}
                            onChange={(appearance) => {
                                setProductTourFormValue('content', {
                                    ...productTourForm.content,
                                    appearance,
                                })
                            }}
                        />
                    ) : (
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
                    ))}
            </SceneContent>
        </Form>
    )
}
