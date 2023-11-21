import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconClose, IconOpenInNew, IconPlus } from 'lib/lemon-ui/icons'
import { BuilderHog3, DetectiveHog } from '../hedgehogs'
import { userLogic } from 'scenes/userLogic'
import { useActions } from 'kea'
import { ProductKey } from '~/types'

export const ProductIntroduction = ({
    productName,
    productKey,
    thingName,
    description,
    titleOverride,
    isEmpty,
    action,
    actionElementOverride,
    docsURL,
    customHog: CustomHog,
}: {
    /** The name of the product, e.g. "Cohorts" */
    productName: string
    productKey: ProductKey
    /** The name of the thing that they will create, e.g. "cohort" */
    thingName: string
    description: string
    /** If you want to override the title, defaults to "Create your first *thing*" */
    titleOverride?: string
    /** If we should show the empty state */
    isEmpty?: boolean
    /** The action to take when the user clicks the CTA */
    action?: () => void
    /** If you want to provide a custom action button instead of using the default one */
    actionElementOverride?: JSX.Element
    docsURL?: string
    customHog?: React.ComponentType<{ className?: string }>
}): JSX.Element => {
    const { updateHasSeenProductIntroFor } = useActions(userLogic)
    const actionable = action || actionElementOverride
    return (
        <div className="border-2 border-dashed border-border w-full p-8 justify-center rounded-md mt-2 mb-4">
            {!isEmpty && (
                <div className="flex justify-end -mb-6 -mt-2 -mr-2">
                    <div>
                        <LemonButton
                            icon={<IconClose />}
                            type="tertiary"
                            status="stealth"
                            onClick={() => {
                                updateHasSeenProductIntroFor(productKey, true)
                            }}
                        />
                    </div>
                </div>
            )}
            <div className="flex items-center gap-x-8 w-full justify-center">
                <div>
                    <div className="w-50 mx-auto mb-4">
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
                    <div className="flex items-center gap-x-4 mt-6">
                        {action ? (
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => {
                                    updateHasSeenProductIntroFor(productKey, true)
                                    action && action()
                                }}
                                data-attr={'create-' + thingName.replace(' ', '-').toLowerCase()}
                            >
                                Create {thingName}
                            </LemonButton>
                        ) : (
                            actionElementOverride
                        )}
                        {docsURL && (
                            <LemonButton
                                type={actionable ? 'tertiary' : 'secondary'}
                                status="muted"
                                sideIcon={<IconOpenInNew className="w-4 h-4" />}
                                to={`${docsURL}?utm_medium=in-product&utm_campaign=empty-state-docs-link`}
                                data-attr="product-introduction-docs-link"
                                targetBlank
                            >
                                Learn more about {productName}
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
