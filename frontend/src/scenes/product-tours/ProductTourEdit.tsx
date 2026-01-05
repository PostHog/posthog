import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect, useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonInputSelect,
    LemonSelect,
    LemonSwitch,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { SurveyMatchTypeLabels } from 'scenes/surveys/constants'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType, SurveyMatchType } from '~/types'

import { AutoShowSection } from './components/AutoShowSection'
import { EditInToolbarButton } from './components/EditInToolbarButton'
import { ProductTourCustomization } from './components/ProductTourCustomization'
import { ProductTourEditTab, productTourLogic } from './productTourLogic'

function InlineCode({ text }: { text: string }): JSX.Element {
    return <code className="border border-1 border-primary rounded-xs px-1 py-0.5 text-xs">{text}</code>
}

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

    // Load recent URLs from property definitions
    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const urlOptions = options['$current_url']

    useEffect(() => {
        if (urlOptions?.status !== 'loading' && urlOptions?.status !== 'loaded') {
            loadPropertyValues({
                endpoint: undefined,
                type: PropertyDefinitionType.Event,
                propertyKey: '$current_url',
                newInput: '',
                eventNames: [],
                properties: [],
            })
        }
    }, [urlOptions?.status, loadPropertyValues])

    const urlMatchTypeOptions = useMemo(() => {
        return Object.entries(SurveyMatchTypeLabels).map(([key, label]) => ({
            label,
            value: key as SurveyMatchType,
        }))
    }, [])

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

                <LemonTabs
                    activeKey={editTab}
                    onChange={(newTab) => setEditTab(newTab as ProductTourEditTab)}
                    tabs={[
                        { key: ProductTourEditTab.Configuration, label: 'Configuration' },
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

                        <LemonField name="description" label="Description">
                            <LemonInput
                                placeholder="Optional description"
                                value={productTourForm.description}
                                onChange={(value) => setProductTourFormValue('description', value)}
                            />
                        </LemonField>

                        <LemonDivider />

                        <div>
                            <h3 className="font-semibold mb-4">
                                Tour URLs&nbsp;
                                <Tooltip title="Tour will only display on URLs matching these conditions.">
                                    <IconInfo />
                                </Tooltip>
                            </h3>
                            <div className="flex gap-2">
                                <LemonSelect
                                    value={conditions.urlMatchType || SurveyMatchType.Contains}
                                    onChange={(value) => {
                                        setProductTourFormValue('content', {
                                            ...productTourForm.content,
                                            conditions: {
                                                ...conditions,
                                                urlMatchType: value,
                                            },
                                        })
                                    }}
                                    options={urlMatchTypeOptions}
                                />
                                <LemonInputSelect
                                    className="flex-1"
                                    mode="single"
                                    value={conditions.url ? [conditions.url] : []}
                                    onChange={(val) => {
                                        setProductTourFormValue('content', {
                                            ...productTourForm.content,
                                            conditions: {
                                                ...conditions,
                                                url: val[0] || undefined,
                                            },
                                        })
                                    }}
                                    onInputChange={(newInput) => {
                                        loadPropertyValues({
                                            type: PropertyDefinitionType.Event,
                                            endpoint: undefined,
                                            propertyKey: '$current_url',
                                            newInput: newInput.trim(),
                                            eventNames: [],
                                            properties: [],
                                        })
                                    }}
                                    placeholder="e.g. /dashboard or https://example.com/app"
                                    allowCustomValues
                                    loading={urlOptions?.status === 'loading'}
                                    options={(urlOptions?.values || []).map(({ name }) => ({
                                        key: String(name),
                                        label: String(name),
                                        value: String(name),
                                    }))}
                                    data-attr="product-tour-url-input"
                                />
                            </div>
                            {conditions.urlMatchType === SurveyMatchType.Exact && (
                                <div className="flex flex-col gap-2 mt-2 text-secondary text-sm">
                                    <p className="m-0">
                                        When using <InlineCode text="= equals" />, trailing slashes will be removed
                                        before URL comparison.
                                    </p>
                                    <p className="m-0">
                                        Example: <InlineCode text="https://posthog.com/" /> will also match{' '}
                                        <InlineCode text="https://posthog.com" />, and vice versa.
                                    </p>
                                </div>
                            )}
                        </div>

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

                                            <LemonDivider />

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
