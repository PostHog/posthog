import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { hogFunctionConfigurationLogic } from './configuration/hogFunctionConfigurationLogic'

export function QuillHogFunctionSceneActions(): JSX.Element {
    const {
        configuration,
        logicProps,
        isLegacyPlugin,
        configurationChanged,
        template,
        isConfigurationSubmitting,
        willReEnableOnSave,
        willChangeEnabledOnSave,
        hogFunction,
    } = useValues(hogFunctionConfigurationLogic)
    const { duplicate, deleteHogFunction, resetForm, submitConfiguration } = useActions(hogFunctionConfigurationLogic)

    return (
        <>
            {!logicProps.templateId && (
                <DropdownMenu>
                    <DropdownMenuTrigger render={<Button size="icon" aria-label="More" tooltip="More" />}>
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        {!isLegacyPlugin && (
                            <>
                                <DropdownMenuItem onClick={() => duplicate()}>Duplicate</DropdownMenuItem>
                                <DropdownMenuSeparator />
                            </>
                        )}
                        <DropdownMenuItem variant="destructive" onClick={() => deleteHogFunction()}>
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            {configurationChanged ? (
                <Button
                    variant="outline"
                    type="reset"
                    onClick={() => resetForm()}
                    disabledReason={isConfigurationSubmitting ? 'Saving in progress…' : undefined}
                >
                    Clear changes
                </Button>
            ) : null}
            <Button
                variant="primary"
                type="submit"
                onClick={submitConfiguration}
                loading={isConfigurationSubmitting}
                disabledReason={!configurationChanged && hogFunction ? 'No changes' : undefined}
            >
                {template ? 'Create' : 'Save'}
                {willReEnableOnSave
                    ? ' & re-enable'
                    : willChangeEnabledOnSave
                      ? ` & ${configuration.enabled ? 'enable' : 'disable'}`
                      : ''}
            </Button>
        </>
    )
}
