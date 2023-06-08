import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconArrowRight, IconOpenInNew, IconPlus } from 'lib/lemon-ui/icons'
import { BuilderHog3, DetectiveHog } from '../hedgehogs'

export const ProductIntroduction = ({
    productName,
    thingName,
    description,
    isEmpty,
    action,
    actionElementOverride,
    docsURL,
}: {
    /** The name of the product, e.g. "Cohorts" */
    productName: string
    /** The name of the thing that they will create, e.g. "cohort" */
    thingName: string
    description: string
    isEmpty?: boolean
    /** The action to take when the user clicks the CTA */
    action?: () => void
    /** If you want to provide a custom action button instead of using the default one */
    actionElementOverride?: JSX.Element
    docsURL?: string
}): JSX.Element => {
    const actionable = action || actionElementOverride
    return (
        <div className="border-2 border-dashed border-border w-full p-8 flex justify-center rounded-md mt-2">
            <div className="flex items-center gap-x-8">
                <div>
                    <div className="w-40 mx-auto mb-4">
                        {actionable ? (
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
                            ? `Create your first ${thingName}`
                            : `No ${thingName}s yet`}
                    </h2>
                    <p className="ml-0">{description}</p>
                    {!isEmpty && (
                        <p className="ml-0">
                            Your team has already started using {productName}. You can jump in to see what your team has
                            made, or create a new one yourself.
                        </p>
                    )}
                    <div className="flex items-center gap-x-4 mt-6">
                        {!isEmpty && (
                            <LemonButton
                                type="primary"
                                sideIcon={<IconArrowRight />}
                                onClick={action}
                                data-attr={'create-' + thingName.replace(' ', '-').toLowerCase()}
                            >
                                Go to {productName}
                            </LemonButton>
                        )}
                        {action ? (
                            <LemonButton
                                type={isEmpty ? 'primary' : 'secondary'}
                                sideIcon={<IconPlus />}
                                onClick={action}
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
                                status="muted-alt"
                                sideIcon={<IconOpenInNew className="w-4 h-4" />}
                                to={`${docsURL}?utm_medium=in-product&utm_campaign=empty-state-docs-link`}
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
