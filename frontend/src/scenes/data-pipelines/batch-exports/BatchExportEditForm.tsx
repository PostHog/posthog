import { IconInfo } from '@posthog/icons'
import { LemonCalendarSelectInput, LemonCheckbox, LemonInput, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { DESTINATIONS } from './destinations'
import { BatchExportConfigurationForm } from './types'

export function BatchExportGeneralEditFields({
    isNew,
    isPipeline = false,
    batchExportConfigForm,
}: {
    isNew: boolean
    isPipeline?: boolean
    batchExportConfigForm: BatchExportConfigurationForm
}): JSX.Element {
    return (
        <div>
            {!isPipeline && (
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Name your workflow for future reference" />
                </LemonField>
            )}
            <div className="flex flex-wrap gap-2 items-start">
                {(!isPipeline || batchExportConfigForm.end_at) && ( // Not present in the new UI unless grandfathered in
                    <LemonField
                        name="end_at"
                        label="End date"
                        className="flex-1"
                        info={
                            <>
                                The date up to which data is to be exported. Leaving it unset implies that data exports
                                will continue forever until this export is paused or deleted.
                            </>
                        }
                    >
                        {({ value, onChange }) => (
                            <LemonCalendarSelectInput
                                value={value}
                                onChange={onChange}
                                placeholder="Select end date (optional)"
                                clearable
                            />
                        )}
                    </LemonField>
                )}
            </div>

            {isNew && !isPipeline ? (
                <LemonField name="paused">
                    <LemonCheckbox
                        bordered
                        label={
                            <span className="flex gap-2 items-center">
                                Create in paused state
                                <Tooltip
                                    title={
                                        <>
                                            If selected, the batch export will be created, but no runs will be
                                            automatically triggered until it is resumed. Manual backfills can still be
                                            triggered even if the batch export is paused.
                                        </>
                                    }
                                >
                                    <IconInfo className="text-lg text-secondary" />
                                </Tooltip>
                            </span>
                        }
                    />
                </LemonField>
            ) : null}
        </div>
    )
}

// Per-destination field rendering is owned by the registry under ./destinations/.
// To add a new destination, create a new file there and register it in destinations/index.ts.
export function BatchExportsEditFields({
    isNew,
    batchExportConfigForm,
    configurationChanged,
}: {
    isNew: boolean
    batchExportConfigForm: BatchExportConfigurationForm
    configurationChanged: boolean
}): JSX.Element {
    const destination = batchExportConfigForm.destination
    const definition = destination ? DESTINATIONS[destination] : undefined

    return (
        <div className="flex flex-col gap-y-4 max-w-200">
            {definition && (
                <definition.Fields
                    isNew={isNew}
                    formValues={batchExportConfigForm}
                    configurationChanged={configurationChanged}
                />
            )}
        </div>
    )
}
