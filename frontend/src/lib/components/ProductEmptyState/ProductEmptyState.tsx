import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconOpenInNew, IconPlus } from 'lib/lemon-ui/icons'

export const ProductEmptyState = ({
    productName,
    thingName,
    description,
    actionable = true,
    action,
    actionOverride,
    docsURL,
}: {
    // The name of the product, e.g. "Cohorts"
    productName: string
    // The name of the thing that they will create, e.g. "cohort"
    thingName: string
    description: string
    actionable?: boolean
    // The action to take when the user clicks the CTA
    action?: () => void
    // If you want to provide a custom action button instead of using the default one
    actionOverride?: JSX.Element
    docsURL?: string
}): JSX.Element => {
    return (
        <div className="border-2 border-dashed border-border-light w-full p-8 flex justify-center rounded-md mt-8">
            <div className="max-w-160 text-center">
                <h2>{actionable ? `Create your first ${thingName}` : `No ${thingName}s yet`}</h2>
                <p>{description}</p>
                <div className="flex justify-center items-center gap-x-4 mt-6">
                    {docsURL && (
                        <LemonButton
                            type="tertiary"
                            status="muted-alt"
                            sideIcon={<IconOpenInNew className="w-4 h-4" />}
                            to={docsURL}
                        >
                            Learn more about {productName}
                        </LemonButton>
                    )}
                    {action && (
                        <LemonButton type="primary" sideIcon={<IconPlus />} onClick={action}>
                            Create a {thingName}
                        </LemonButton>
                    )}
                    {actionOverride && actionOverride}
                </div>
            </div>
        </div>
    )
}
