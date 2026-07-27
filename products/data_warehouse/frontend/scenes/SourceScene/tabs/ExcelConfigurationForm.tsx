import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EXCEL_UPLOAD_ACCEPT } from '../../NewSourceScene/excelSourceLogic'
import { sourceSettingsLogic } from './sourceSettingsLogic'

/**
 * Replaces the generic configuration form for the Excel source. The generic form would render the
 * source's raw reference fields (upload id, stored filename) as editable inputs — hand-editing
 * those can only break the reference. What a workbook source actually needs is: see the current
 * file, upload a replacement (which re-imports its sheets), and the generic description/auto-sync
 * settings.
 */
export function ExcelConfigurationForm(): JSX.Element {
    const { source, sourceConfig, sourceConfigLoading, excelWorkbookUploading } = useValues(sourceSettingsLogic)
    const { uploadNewExcelWorkbook } = useActions(sourceSettingsLogic)

    if (!source) {
        return <></>
    }

    const currentFilename = (source.job_inputs?.filename as string | undefined) ?? 'workbook.xlsx'

    return (
        <div className="flex flex-col gap-4">
            <div>
                <div className="font-semibold mb-1">Workbook</div>
                <div className="text-sm text-muted mb-2">
                    Currently imported from <strong>{currentFilename}</strong>. Upload a new version to replace it — its
                    sheets are re-imported and the tables are rebuilt from the new file.
                </div>
                <LemonFileInput
                    multiple={false}
                    accept={EXCEL_UPLOAD_ACCEPT}
                    value={[]}
                    loading={excelWorkbookUploading}
                    disabledReason={excelWorkbookUploading ? 'Uploading the new workbook' : undefined}
                    onChange={(files) => files[0] && uploadNewExcelWorkbook(files[0])}
                    callToAction={
                        <div className="flex items-center gap-2">
                            {excelWorkbookUploading ? <Spinner /> : null}
                            <span>{excelWorkbookUploading ? 'Uploading…' : 'Upload a new version'}</span>
                        </div>
                    }
                />
            </div>

            <LemonDivider />

            <Form logic={sourceSettingsLogic} formKey="sourceConfig" enableFormOnSubmit>
                <div className="flex flex-col gap-2">
                    <LemonField name="description" label="Description (optional)">
                        {({ value, onChange }) => (
                            <LemonInput
                                value={value ?? ''}
                                onChange={onChange}
                                placeholder="e.g. Monthly revenue workbook"
                                data-attr="excel-source-description"
                            />
                        )}
                    </LemonField>

                    <LemonField
                        name="auto_sync_new_schemas"
                        help="Sheets added to a newly uploaded version of the workbook will be imported automatically."
                    >
                        {({ value, onChange }) => (
                            <LemonSwitch
                                bordered
                                checked={value ?? false}
                                onChange={onChange}
                                label="Automatically import new sheets"
                                data-attr="excel-source-auto-sync-new-schemas"
                            />
                        )}
                    </LemonField>
                </div>

                <div className="my-4 flex flex-row justify-end gap-2">
                    <AccessControlAction
                        resourceType={AccessControlResourceType.ExternalDataSource}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={source.user_access_level}
                    >
                        <LemonButton
                            loading={sourceConfigLoading}
                            disabledReason={sourceConfig ? undefined : 'Loading configuration'}
                            type="primary"
                            center
                            htmlType="submit"
                            data-attr="excel-source-update"
                        >
                            Save
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </Form>
        </div>
    )
}
