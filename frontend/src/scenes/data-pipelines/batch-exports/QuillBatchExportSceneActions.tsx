import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { batchExportConfigFormLogic, getDefaultConfiguration } from './batchExportConfigFormLogic'

export function QuillBatchExportSceneActions(): JSX.Element {
    const { isNew, isConfigurationSubmitting, configurationChanged, savedConfiguration, service } =
        useValues(batchExportConfigFormLogic)
    const { deleteBatchExport, resetConfiguration, submitConfiguration } = useActions(batchExportConfigFormLogic)

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button size="icon" aria-label="More" tooltip="More" />}>
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuItem variant="destructive" onClick={() => deleteBatchExport()}>
                        Delete
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            {configurationChanged ? (
                <Button
                    variant="outline"
                    type="reset"
                    onClick={() =>
                        isNew && service
                            ? resetConfiguration(getDefaultConfiguration(service))
                            : resetConfiguration(savedConfiguration)
                    }
                    disabledReason={isConfigurationSubmitting ? 'Saving in progress…' : undefined}
                >
                    {isNew ? 'Reset' : 'Clear changes'}
                </Button>
            ) : null}
            <Button
                variant="primary"
                type="submit"
                onClick={submitConfiguration}
                loading={isConfigurationSubmitting}
                disabledReason={
                    !configurationChanged
                        ? 'No changes to save'
                        : isConfigurationSubmitting
                          ? 'Saving in progress…'
                          : undefined
                }
            >
                {isNew ? 'Create' : 'Save'}
            </Button>
        </>
    )
}
