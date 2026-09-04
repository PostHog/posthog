import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanizeBytes } from 'lib/utils/numbers'

import { FILE_UPLOAD_ACCEPT, fileUploadSourceLogic } from '../fileUploadSourceLogic'

export function FileUploadSourceForm(): JSX.Element {
    const { fileUpload, isFileUploadSubmitting, uploadStage, uploadPercent } = useValues(fileUploadSourceLogic)
    const { selectFiles, setTableName, setFileFormat } = useActions(fileUploadSourceLogic)

    const busyReason = !isFileUploadSubmitting
        ? undefined
        : uploadStage === 'create_table'
          ? 'Creating your table'
          : 'Uploading your file'

    return (
        <Form
            formKey="fileUpload"
            logic={fileUploadSourceLogic}
            className="deprecated-space-y-4"
            enableFormOnSubmit
            autoComplete="off"
        >
            <div className="flex flex-col gap-2">
                <LemonField name="file_format" label="File format" className="w-max">
                    {({ value }) => (
                        <LemonSelect
                            data-attr="file-upload-format"
                            options={[
                                { label: 'CSV', value: 'csv' },
                                { label: 'JSON', value: 'json' },
                                { label: 'Parquet', value: 'parquet' },
                            ]}
                            value={value}
                            onChange={setFileFormat}
                            disabledReason={busyReason}
                        />
                    )}
                </LemonField>

                <LemonField name="files" label="File">
                    {({ value }) => (
                        <LemonFileInput
                            multiple={false}
                            accept={FILE_UPLOAD_ACCEPT[fileUpload.file_format]}
                            value={value}
                            onChange={selectFiles}
                            disabledReason={busyReason}
                        />
                    )}
                </LemonField>
                <div className="mb-4 text-xs text-secondary">Files can be up to 50MB.</div>

                <LemonField name="table_name" label="Table name">
                    {({ value = '' }) => (
                        <LemonInput
                            data-attr="file-upload-table-name"
                            className="ph-ignore-input"
                            placeholder="Examples: monthly_revenue, customer_list"
                            autoComplete="off"
                            autoCapitalize="off"
                            autoCorrect="off"
                            spellCheck={false}
                            value={value}
                            onChange={setTableName}
                            disabled={isFileUploadSubmitting}
                        />
                    )}
                </LemonField>
                <div className="mb-4 text-xs text-secondary">
                    This will be the table name used when writing queries. Use only letters, numbers, and underscores,
                    and start with a letter or underscore.
                </div>
            </div>

            {uploadStage === 'upload' ? (
                <div className="flex flex-col gap-1" data-attr="file-upload-progress">
                    <LemonProgress percent={uploadPercent} />
                    <div className="text-xs text-secondary">
                        Uploading file: {uploadPercent}% of {humanizeBytes(fileUpload.files[0]?.size ?? null)}
                    </div>
                </div>
            ) : uploadStage === 'create_table' ? (
                <div className="flex items-center gap-2 text-xs text-secondary" data-attr="file-upload-progress">
                    <Spinner />
                    File uploaded. Creating the table.
                </div>
            ) : null}

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isFileUploadSubmitting}
                    disabledReason={busyReason}
                    data-attr="file-upload-submit"
                >
                    Upload and create table
                </LemonButton>
            </div>
        </Form>
    )
}
