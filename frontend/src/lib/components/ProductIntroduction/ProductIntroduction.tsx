import { useActions, useValues } from 'kea'

import { IconOpenSidebar, IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'

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
    /**
     * Default hides the hog below `md`. Use `responsive` to keep the hog visible on small screens with a vertical
     * layout (hog above copy), switching to the horizontal layout from `md` up (or from `main-content` width when
     * `useMainContentContainerQueries` is set).
     */
    hogLayout?: 'default' | 'responsive'
    /**
     * When set with `hogLayout="responsive"`, use the `main-content` container (see Navigation) instead of the
     * viewport for breakpoints so layout responds when the side panel narrows the main column.
     */
    useMainContentContainerQueries?: boolean
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
    hogLayout = 'default',
    useMainContentContainerQueries = false,
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
    const isResponsiveHogLayout = hogLayout === 'responsive'

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
            <div
                className={cn(
                    'flex w-full justify-center',
                    isResponsiveHogLayout
                        ? useMainContentContainerQueries
                            ? 'flex-col @min-[48rem]/main-content:flex-row items-center gap-6 @min-[48rem]/main-content:gap-8'
                            : 'flex-col md:flex-row items-center gap-6 md:gap-8'
                        : 'flex-row items-center gap-8'
                )}
            >
                <div
                    className={cn(
                        isResponsiveHogLayout &&
                            (useMainContentContainerQueries
                                ? 'w-full @min-[48rem]/main-content:w-auto flex justify-center'
                                : 'w-full md:w-auto flex justify-center')
                    )}
                >
                    <div
                        className={cn(
                            'mx-auto',
                            isResponsiveHogLayout
                                ? useMainContentContainerQueries
                                    ? 'block w-36 sm:w-40 lg:w-50 mb-4 @min-[48rem]/main-content:mb-0'
                                    : 'block w-36 sm:w-40 lg:w-50 mb-4 md:mb-0'
                                : 'w-40 lg:w-50 mb-4 hidden md:block'
                        )}
                    >
                        {CustomHog ? (
                            <CustomHog className="w-full h-full" />
                        ) : actionable ? (
                            <BuilderHog3 className="w-full h-full" />
                        ) : (
                            <DetectiveHog className="w-full h-full" />
                        )}
                    </div>
                </div>
                <div
                    className={cn(
                        'flex-shrink max-w-140',
                        isResponsiveHogLayout &&
                            (useMainContentContainerQueries
                                ? 'w-full text-center @min-[48rem]/main-content:text-left'
                                : 'w-full text-center md:text-left')
                    )}
                >
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
                    <div
                        className={cn(
                            'flex items-center gap-x-4 gap-y-2 mt-6 flex-wrap',
                            isResponsiveHogLayout &&
                                (useMainContentContainerQueries
                                    ? 'justify-center @min-[48rem]/main-content:justify-start'
                                    : 'justify-center md:justify-start')
                        )}
                    >
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
