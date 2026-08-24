import { InlineSourceSetup } from 'products/data_warehouse/frontend/shared/components/InlineSourceSetup'

/**
 * Featured data warehouse sources (Stripe, ad platforms, Postgres, GitHub, ...) with the full
 * catalog behind an expand. Connecting a source is the step's primary action; the footer only
 * offers Skip. Ad platforms have no other onboarding surface, so this step is their entry point.
 */
export function SourcesStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    return (
        <InlineSourceSetup
            onComplete={onContinue}
            featured
            showWizard
            autoConfigureTables
            subtitle="Link sources like Stripe, Google Ads, and Postgres to query them alongside your product data. You can always connect more sources later."
        />
    )
}
