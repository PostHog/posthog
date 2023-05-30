import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconOpenInNew, IconPlus } from 'lib/lemon-ui/icons'
import { BuilderHog3, DetectiveHog } from '../hedgehogs'

export const ProductEmptyState = ({
    productName,
    thingName,
    description,
    action,
    actionElementOverride,
    docsURL,
    customHog,
}: {
    // The name of the product, e.g. "Cohorts"
    productName: string
    // The name of the thing that they will create, e.g. "cohort"
    thingName: string
    description: string
    // The action to take when the user clicks the CTA
    action?: () => void
    // If you want to provide a custom action button instead of using the default one
    actionElementOverride?: JSX.Element
    docsURL?: string
    customHog?: JSX.Element
}): JSX.Element => {
    const actionable = action || actionElementOverride
    return (
        <div className="border-2 border-dashed border-border-light w-full p-8 flex justify-center rounded-md mt-6">
            <div className="flex items-center gap-x-8">
                <div>
                    <div className="w-40 mx-auto mb-4">
                        {customHog ? (
                            { customHog }
                        ) : actionable ? (
                            <BuilderHog3 className="w-full h-full" />
                        ) : (
                            <DetectiveHog className="w-full h-full" />
                        )}
                    </div>
                </div>
                <div className="flex-shrink max-w-140">
                    <h2>{actionable ? `Create your first ${thingName}` : `No ${thingName}s yet`}</h2>
                    <p className="ml-0">{description}</p>
                    <div className="flex items-center gap-x-4 mt-6">
                        {action ? (
                            <LemonButton
                                type="primary"
                                sideIcon={<IconPlus />}
                                onClick={action}
                                data-attr={'create-' + thingName.replace(' ', '-').toLowerCase()}
                            >
                                Create {thingName}
                            </LemonButton>
                        ) : (
                            actionElementOverride && actionElementOverride
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
