import { IconPlusSmall } from '@posthog/icons'
import { BindLogic, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { MessagingTabs } from 'scenes/messaging/MessagingTabs'
import { providersLogic } from 'scenes/messaging/providersLogic'
import { DestinationsTable } from 'scenes/pipeline/destinations/Destinations'
import { pipelineDestinationsLogic } from 'scenes/pipeline/destinations/destinationsLogic'
import { HogFunctionConfiguration } from 'scenes/pipeline/hogfunctions/HogFunctionConfiguration'
import { HogFunctionTemplateList } from 'scenes/pipeline/hogfunctions/list/HogFunctionTemplateList'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export function Providers(): JSX.Element {
    const { providerId, templateId } = useValues(providersLogic)
    return (
        <>
            <MessagingTabs key="tabs" />
            {providerId ? (
                <HogFunctionConfiguration id={providerId === 'new' ? null : providerId} templateId={templateId} />
            ) : (
                <>
                    <PageHeader
                        caption="Configure e-mail, SMS and other messaging providers here"
                        buttons={
                            <LemonButton
                                data-attr="new-provider"
                                to={urls.messagingProviderNew()}
                                type="primary"
                                icon={<IconPlusSmall />}
                            >
                                New provider
                            </LemonButton>
                        }
                    />
                    <BindLogic logic={pipelineDestinationsLogic} props={{ type: 'email' }}>
                        <DestinationsTable />
                    </BindLogic>
                    <div className="mt-4" />
                    <h2>Add Provider</h2>
                    <HogFunctionTemplateList defaultFilters={{}} type="email" />
                </>
            )}
        </>
    )
}
export const scene: SceneExport = {
    component: Providers,
    logic: providersLogic,
}
