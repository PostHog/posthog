import { useActions, useValues } from 'kea'

import { IconOpenSidebar, IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/types'

import { BuilderHog3, DetectiveHog } from '../hedgehogs'

/**
 * A component to introduce new users to a product, and to show something
 * other than an empty table when there are no items.
 * Not to be confused with the `OnboardingProductIntroduction` scene,
 * which is shown when a team has yet to go through onboarding for the product.
 */

export type ProductIntroductionProps = {
    /** The name of the product, e.g. "Cohorts" */
    productName: string
    productKey?: ProductKey
    /** The name of the thing that they will create, e.g. "cohort" */
    thingName: string
    description: string
    /** If you want to override the title, defaults to "Create your first *thing*" */
    titleOverride?: string
    /** If we should show the empty state */
    isEmpty?: boolean
    /** The action to take when the user clicks the CTA */
    action?: () => void
    disabledReason?: string
    /** If you want to provide a custom action button instead of using the default one */
    actionElementOverride?: JSX.Element
    docsURL?: string
    customHog?: React.ComponentType<{ className?: string }>
    className?: string
}

export const ProductIntroduction = ({
    productName,
    productKey,
    thingName,
    description,
    titleOverride,
    isEmpty,
    action,
    disabledReason,
    actionElementOverride,
    docsURL,
    customHog: CustomHog,
    className,
}: ProductIntroductionProps): JSX.Element | null => {
    const { updateHasSeenProductIntroFor } = useActions(userLogic)
    const { user } = useValues(userLogic)

    if (!user) {
        return null
    }

    if (!isEmpty && (!productKey || user.has_seen_product_intro_for?.[productKey])) {
        // Hide if its not an empty list but the user has seen it before
        return null
    }

    const actionable = action || actionElementOverride
    return (
        <div
            className={cn(
                'border-2 border-dashed border-primary w-full p-8 justify-center rounded mt-2 mb-4',
                className
            )}
            data-attr={`product-introduction-${thingName}`}
        >
            {!isEmpty && (
                <div className="flex justify-end -mb-6 -mt-2 -mr-2">
                    <div>
                        <LemonButton
                            icon={<IconX />}
                            size="small"
                            onClick={() => {
                                productKey && updateHasSeenProductIntroFor(productKey)
                            }}
                        />
                    </div>
                </div>
            )}
            <div className="flex items-center gap-8 w-full justify-center">
                <div>
                    <div className="w-40 lg:w-50 mx-auto mb-4 hidden md:block">
                        {CustomHog ? (
                            <CustomHog className="w-full h-full" />
                        ) : actionable ? (
                            <BuilderHog3 className="w-full h-full" />
                        ) : (
                            <DetectiveHog className="w-full h-full" />
                        )}
                    </div>
                </div>
                <div className="flex-shrink max-w-140">
                    <h2>
                        {!isEmpty
                            ? `Welcome to ${productName}!`
                            : actionable
                              ? titleOverride
                                  ? titleOverride
                                  : `Create your first ${thingName}`
                              : `No ${thingName}s yet`}
                    </h2>
                    <p className="ml-0">{description}</p>
                    {!isEmpty && (
                        <p className="ml-0">
                            Your team is already using {productName}. You can take a look at what they're doing, or get
                            started yourself.
                        </p>
                    )}
                    <div className="flex items-center gap-x-4 gap-y-2 mt-6 flex-wrap">
                        {action ? (
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => {
                                    productKey && updateHasSeenProductIntroFor(productKey)
                                    action?.()
                                }}
                                data-attr={'create-' + thingName.replace(' ', '-').toLowerCase()}
                                disabledReason={disabledReason}
                            >
                                Create {thingName}
                            </LemonButton>
                        ) : (
                            actionElementOverride
                        )}
                        {docsURL && (
                            <LemonButton
                                type={actionable ? 'tertiary' : 'secondary'}
                                sideIcon={<IconOpenSidebar className="w-4 h-4" />}
                                to={`${docsURL}?utm_medium=in-product&utm_campaign=empty-state-docs-link`}
                                data-attr="product-introduction-docs-link"
                                targetBlank
                            >
                                Learn more
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
