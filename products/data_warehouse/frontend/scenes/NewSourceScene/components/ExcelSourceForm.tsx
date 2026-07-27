import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconUpload } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, Link, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { EXCEL_UPLOAD_ACCEPT, excelSourceLogic } from '../excelSourceLogic'
import { type SourceWizardLogicProps, sourceWizardLogic } from '../sourceWizardLogic'

/**
 * Replaces the generic connection form for the Excel source: the "credential" here is an uploaded
 * workbook, so the user picks a file and the upload fills the wizard's payload. Prefix and
 * description bind to the same `sourceConnectionDetails` form the generic step uses — the prefix
 * matters because a second Excel source needs one to keep its table names from clashing.
 * Everything after this step (sheet selection, column selection) is the standard wizard flow.
 */
export function ExcelSourceForm({
    sourceWizardLogicProps,
}: {
    sourceWizardLogicProps?: SourceWizardLogicProps
}): JSX.Element {
    const { selectedConnector } = useValues(sourceWizardLogic)
    const { uploading, uploadedFilename } = useValues(excelSourceLogic)
    const { selectFiles } = useActions(excelSourceLogic)

    return (
        <Form
            logic={sourceWizardLogic}
            props={sourceWizardLogicProps}
            formKey="sourceConnectionDetails"
            enableFormOnSubmit
            className="deprecated-space-y-4"
        >
            {selectedConnector?.caption && (
                <LemonMarkdown className="text-sm">{selectedConnector.caption}</LemonMarkdown>
            )}

            <LemonField.Pure label="Workbook">
                <LemonFileInput
                    multiple={false}
                    accept={EXCEL_UPLOAD_ACCEPT}
                    value={[]}
                    disabledReason={uploading ? 'Uploading your workbook' : undefined}
                    onChange={selectFiles}
                    callToAction={
                        <LemonButton
                            icon={uploading ? <Spinner /> : <IconUpload />}
                            type="secondary"
                            disabledReason={uploading ? 'Uploading your workbook' : undefined}
                        >
                            {uploading ? 'Uploading…' : 'Click or drag and drop to upload (.xlsx, .xlsm)'}
                        </LemonButton>
                    }
                />
                <div className="text-xs text-secondary">Files can be up to 50MB.</div>
            </LemonField.Pure>

            {uploadedFilename && !uploading && (
                <LemonBanner type="success">
                    Uploaded <strong>{uploadedFilename}</strong>. Continue to pick which sheets to import — each one
                    becomes its own table.
                </LemonBanner>
            )}

            <LemonField
                name="prefix"
                label="Table prefix (optional)"
                help="Use only letters, numbers, and underscores. Must start with a letter or underscore. Required if you already have another Excel source, so their table names don't clash."
            >
                {({ value, onChange }) => {
                    const cleaned = value ? value.trim().replace(/^_+|_+$/g, '') : ''
                    const tableName = (cleaned ? `excel.${cleaned}.sheet_name` : `excel.sheet_name`).toLowerCase()
                    return (
                        <>
                            <LemonInput
                                className="ph-ignore-input"
                                data-attr="excel-prefix"
                                placeholder="monthly_revenue"
                                value={value}
                                onChange={onChange}
                            />
                            <p className="mb-0 text-xs">
                                Table name will look like:&nbsp;<strong>{tableName}</strong>
                            </p>
                        </>
                    )
                }}
            </LemonField>

            <LemonField
                name="description"
                label="Description (optional)"
                help="A description to help you identify this source, e.g. 'Monthly revenue workbook'."
            >
                {({ value, onChange }) => (
                    <LemonInput
                        className="ph-ignore-input"
                        data-attr="excel-description"
                        placeholder="e.g. Monthly revenue workbook"
                        value={value || ''}
                        onChange={onChange}
                    />
                )}
            </LemonField>

            {selectedConnector?.docsUrl && (
                <Link to={selectedConnector.docsUrl} target="_blank" className="text-sm">
                    View docs
                </Link>
            )}
        </Form>
    )
}
