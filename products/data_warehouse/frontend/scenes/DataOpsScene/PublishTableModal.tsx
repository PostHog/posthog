import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { publishedTablesLogic } from './publishedTablesLogic'

export function PublishTableModal(): JSX.Element {
    const { publishModalOpen, modeledTables, modeledTablesLoading, modeledTablesError, isPublishTableSubmitting } =
        useValues(publishedTablesLogic)
    const { closePublishModal, loadModeledTables, submitPublishTable } = useActions(publishedTablesLogic)

    const noModeledTables = modeledTables !== null && modeledTables.length === 0

    return (
        <LemonModal
            isOpen={publishModalOpen}
            title="Publish a modeled table"
            description="Create a snapshot that can be queried with other warehouse data in PostHog."
            onClose={closePublishModal}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closePublishModal}
                        disabled={isPublishTableSubmitting}
                        data-attr="cancel-publish-table"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitPublishTable}
                        loading={isPublishTableSubmitting}
                        data-attr="submit-publish-table"
                        disabledReason={
                            modeledTablesLoading
                                ? 'Modeled tables are still loading'
                                : modeledTablesError
                                  ? 'Reload modeled tables before publishing'
                                  : noModeledTables
                                    ? 'No modeled tables are available to publish'
                                    : undefined
                        }
                    >
                        Publish table
                    </LemonButton>
                </>
            }
        >
            <Form logic={publishedTablesLogic} formKey="publishTable" className="flex flex-col gap-4">
                {modeledTablesError ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadModeledTables }}>
                        {modeledTablesError}
                    </LemonBanner>
                ) : null}
                <LemonField name="sourceTableKey" label="Modeled table">
                    {modeledTablesLoading || modeledTables === null ? (
                        <div className="flex min-h-10 items-center gap-2 text-muted">
                            <Spinner />
                            <span>Loading modeled tables...</span>
                        </div>
                    ) : (
                        <LemonSelect
                            fullWidth
                            placeholder="Select a modeled table"
                            options={modeledTables.map((table) => ({
                                value: `${table.schema_name}.${table.table_name}`,
                                label: `${table.schema_name}.${table.table_name}`,
                            }))}
                        />
                    )}
                </LemonField>
                <LemonField
                    name="name"
                    label="Table name in PostHog"
                    info="Leave blank to generate a name from the schema and modeled table."
                >
                    <LemonInput placeholder="modeled_customers" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
