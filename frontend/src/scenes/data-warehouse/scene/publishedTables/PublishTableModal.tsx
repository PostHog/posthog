import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { publishedTablesLogic } from './publishedTablesLogic'

export function PublishTableModal(): JSX.Element {
    const { publishModalOpen, modeledTables, modeledTablesLoading, modeledTablesError, isPublishTableSubmitting } =
        useValues(publishedTablesLogic)
    const { closePublishModal, submitPublishTable } = useActions(publishedTablesLogic)

    return (
        <LemonModal
            isOpen={publishModalOpen}
            title="Publish a modeled table"
            description="Create a snapshot that can be queried from PostHog. Publish it again whenever the modeled data changes."
            onClose={closePublishModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closePublishModal} disabled={isPublishTableSubmitting}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitPublishTable}
                        loading={isPublishTableSubmitting}
                        disabledReason={
                            modeledTablesLoading
                                ? 'Modeled tables are still loading'
                                : modeledTables.length === 0
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
                {modeledTablesError ? <LemonBanner type="error">{modeledTablesError}</LemonBanner> : null}
                <LemonField name="sourceTableKey" label="Modeled table">
                    {modeledTablesLoading ? (
                        <div className="flex items-center gap-2 text-muted min-h-10">
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
                <LemonField name="name" label="Table name" info="Leave blank to use the schema and modeled table name.">
                    <LemonInput placeholder="main_customers" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
