import * as construction2 from '@posthog/brand/hoggies/png/construction-2'
import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass-1'
import { IconOpenSidebar, IconPlus } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'

const HedgehogConstruction2 = pngHoggie(construction2)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlass)

/**
 * Inline empty panel for one part of a surface: a tab or sub-list, a widget tile, a notebook
 * node, a settings section, an activity log, or a state that is not about setup. It renders
 * where the list would be, so the rest of the surface stays usable around it.
 *
 * A whole product landing scene that is empty because the product is not set up uses the
 * scene-level gate instead: declare {@link SceneExport.emptyState} with a
 * {@link ProductEmptyState} config (see `lib/components/ProductEmptyState/README.md`).
 * Not to be confused with the `OnboardingProductIntroduction` scene, which is shown when a
 * team has yet to go through onboarding for the product.
 */

export type ProductIntroductionProps = {
    /** The name of the thing that they will create, e.g. "cohort" */
    thingName: string
    description: string
    /** If you want to override the title, defaults to "Create your first *thing*" */
    titleOverride?: string
    /**
     * Pass `false` to render nothing while the surface has content. Defaults to `true`. Prefer
     * branching at the call site; this exists so callers can pass their emptiness check through.
     */
    isEmpty?: boolean
    /** The action to take when the user clicks the CTA */
    action?: () => void
    disabledReason?: string
    /** If you want to provide a custom action button instead of using the default one */
    actionElementOverride?: JSX.Element
    docsURL?: string
    customHog?: React.ComponentType<{ className?: string }>
    hogClassName?: string
    className?: string
    /**
     * Default hides the hog below `md`. Use `responsive` to keep the hog visible on small screens with a vertical
     * layout (hog above copy), switching to the horizontal layout from `md` up (or from `main-content` width when
     * `useMainContentContainerQueries` is set). Use `vertical` for always-stacked hog-above-copy (e.g. narrow dashboard tiles).
     */
    hogLayout?: 'default' | 'responsive' | 'vertical'
    /**
     * When set with `hogLayout="responsive"`, use the `main-content` container (see Navigation) instead of the
     * viewport for breakpoints so layout responds when the side panel narrows the main column.
     */
    useMainContentContainerQueries?: boolean
    /**
     * Optional classes for the copy + actions column (hog + this column are siblings). Default `max-w-140`; override
     * for wide empty states (e.g. template grids). Passed through `cn` with tailwind-merge so `max-w-*` replaces default.
     */
    contentClassName?: string
}

export const ProductIntroduction = ({
    thingName,
    description,
    titleOverride,
    isEmpty = true,
    action,
    disabledReason,
    actionElementOverride,
    docsURL,
    customHog: CustomHog,
    hogClassName,
    className,
    hogLayout = 'default',
    useMainContentContainerQueries = false,
    contentClassName,
}: ProductIntroductionProps): JSX.Element | null => {
    if (!isEmpty) {
        return null
    }

    const actionable = action || actionElementOverride
    const isVerticalHogLayout = hogLayout === 'vertical'
    const isResponsiveHogLayout = hogLayout === 'responsive'

    const HogComponent = CustomHog ? CustomHog : actionable ? HedgehogConstruction2 : HedgehogMagnifyingGlass

    return (
        <div
            className={cn(
                'border-2 border-dashed border-primary w-full p-8 justify-center rounded mt-2 mb-4',
                className
            )}
            data-attr={`product-introduction-${thingName}`}
        >
            <div
                className={cn(
                    'flex w-full justify-center',
                    isVerticalHogLayout
                        ? 'flex-col items-center gap-6'
                        : isResponsiveHogLayout
                          ? useMainContentContainerQueries
                              ? 'flex-col @min-[48rem]/main-content:flex-row items-center gap-6 @min-[48rem]/main-content:gap-8'
                              : 'flex-col md:flex-row items-center gap-6 md:gap-8'
                          : 'flex-row items-center gap-8'
                )}
            >
                <div
                    className={cn(
                        isVerticalHogLayout && 'w-full flex justify-center',
                        isResponsiveHogLayout &&
                            (useMainContentContainerQueries
                                ? 'w-full @min-[48rem]/main-content:w-auto flex justify-center'
                                : 'w-full md:w-auto flex justify-center')
                    )}
                >
                    <div
                        className={cn(
                            'mx-auto',
                            isVerticalHogLayout
                                ? 'block w-56 sm:w-60 lg:w-70 mb-4'
                                : isResponsiveHogLayout
                                  ? useMainContentContainerQueries
                                      ? 'block w-56 sm:w-60 lg:w-70 mb-4 @min-[48rem]/main-content:mb-0'
                                      : 'block w-56 sm:w-60 lg:w-70 mb-4 md:mb-0'
                                  : 'w-60 lg:w-70 mb-4 hidden md:block',
                            hogClassName
                        )}
                    >
                        <HogComponent className="w-full h-full" />
                    </div>
                </div>
                <div
                    className={cn(
                        'flex-shrink max-w-140',
                        isVerticalHogLayout && 'w-full text-center',
                        isResponsiveHogLayout &&
                            (useMainContentContainerQueries
                                ? 'w-full text-center @min-[48rem]/main-content:text-left'
                                : 'w-full text-center md:text-left'),
                        contentClassName
                    )}
                >
                    <h2>{actionable ? (titleOverride ?? `Create your first ${thingName}`) : `No ${thingName}s yet`}</h2>
                    <p className="ml-0">{description}</p>
                    <div
                        className={cn(
                            'flex items-center gap-x-4 gap-y-2 mt-6 flex-wrap',
                            isVerticalHogLayout && 'justify-center',
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
                                onClick={action}
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
