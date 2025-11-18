import { useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { SupportHeroHog } from 'lib/components/hedgehogs'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

interface ZendeskSourceSetupPromptProps {
    children: React.ReactNode
    className?: string
}

export function ZendeskSourceSetupPrompt({ children, className }: ZendeskSourceSetupPromptProps): JSX.Element {
    const { hasZendeskSource, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    return dataWarehouseSourcesLoading ? (
        <div className="flex justify-center">
            <Spinner />
        </div>
    ) : !hasZendeskSource ? (
        <SetupPrompt className={className} />
    ) : (
        <>{children}</>
    )
}

function SetupPrompt({ className }: Pick<ZendeskSourceSetupPromptProps, 'className'>): JSX.Element {
    return (
        <ProductIntroduction
            customHog={SupportHeroHog}
            productName="Data Warehouse Source"
            titleOverride="Bring your data from Zendesk"
            productKey={ProductKey.DATA_WAREHOUSE}
            thingName="data source"
            className={className}
            description="Use data warehouse sources to import data from Zendesk into PostHog."
            isEmpty={true}
            docsURL="https://posthog.com/docs/data-warehouse"
            actionElementOverride={
                <LemonButton
                    icon={<IconPlusSmall />}
                    type="primary"
                    to={urls.dataWarehouseSourceNew('Zendesk')}
                    children="Create Zendesk source"
                />
            }
        />
    )
}
