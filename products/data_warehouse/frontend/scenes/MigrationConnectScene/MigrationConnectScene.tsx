import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { migrationConnectSceneLogic } from './migrationConnectSceneLogic'

export const scene: SceneExport = {
    component: MigrationConnectScene,
    logic: migrationConnectSceneLogic,
}

export function MigrationConnectScene(): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { startedMigration, isKeyFormSubmitting } = useValues(migrationConnectSceneLogic)

    if (receivedFeatureFlags && !featureFlags[FEATURE_FLAGS.WAREHOUSE_MIGRATION_IMPORT]) {
        return <NotFound object="page" caption="Importing from Fivetran isn't available for this project yet." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Import from Fivetran"
                resourceType={{ type: 'data_pipeline' }}
                description={
                    startedMigration
                        ? undefined
                        : 'Enter a read-only Fivetran API key. PostHog reads your connectors, destinations, and sync settings to plan the matching PostHog sources. The key is stored encrypted and is never shown again, including to the assistant that sent you here.'
                }
            />
            <div className="max-w-200">
                {startedMigration ? (
                    <LemonBanner type="success">
                        <p className="font-semibold mb-1">Fivetran key saved. You can close this tab.</p>
                        <p className="m-0 text-sm">
                            PostHog is reading your Fivetran account now. Return to your chat and let the assistant know
                            you're done, and it will show you what can move.
                        </p>
                    </LemonBanner>
                ) : (
                    <Form logic={migrationConnectSceneLogic} formKey="keyForm" enableFormOnSubmit className="space-y-4">
                        <p className="m-0 text-sm">
                            Create a system key in Fivetran with read access to connections, destinations, and the
                            account.{' '}
                            <Link to="https://fivetran.com/docs/rest-api/getting-started" target="_blank">
                                How to create a Fivetran API key
                            </Link>
                        </p>
                        <LemonField name="api_key" label="API key">
                            <LemonInput autoComplete="off" data-attr="warehouse-migration-api-key" />
                        </LemonField>
                        <LemonField name="api_secret" label="API secret">
                            <LemonInput type="password" autoComplete="off" data-attr="warehouse-migration-api-secret" />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isKeyFormSubmitting}
                            disabledReason={isKeyFormSubmitting ? 'Checking the key…' : undefined}
                            data-attr="warehouse-migration-save-key"
                        >
                            Save key
                        </LemonButton>
                    </Form>
                )}
            </div>
        </SceneContent>
    )
}
