import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanizeBytes } from 'lib/utils/numbers'

import { FILE_UPLOAD_ACCEPT } from '../../NewSourceScene/fileUploadSourceLogic'
import { replaceFileLogic } from './replaceFileLogic'

export function ReplaceFileModal({ sourceId }: { sourceId: string }): JSX.Element {
    const logic = replaceFileLogic({ sourceId })
    const {
        target,
        isReplaceFileModalOpen,
        file,
        fileFormat,
        fileError,
        replaceError,
        replaceStage,
        isReplacing,
        uploadPercent,
    } = useValues(logic)
    const { closeReplaceFile, selectFile, setFileFormat, submitReplaceFile } = useActions(logic)
    const objectStorageSourcesEnabled = useFeatureFlag('DATA_WAREHOUSE_OBJECT_STORAGE_SOURCES')

    const busyReason = isReplacing ? 'The file is being replaced' : undefined

    return (
        <LemonModal
            isOpen={isReplaceFileModalOpen}
            onClose={isReplacing ? undefined : closeReplaceFile}
            closable={!isReplacing}
            title={target ? `Replace the file of ${target.tableName}` : 'Replace file'}
            description="Upload a new file to replace all rows in this table. The table keeps its name, so your queries keep working."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeReplaceFile}
                        disabledReason={busyReason}
                        data-attr="replace-file-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitReplaceFile}
                        loading={isReplacing}
                        disabledReason={busyReason ?? (!file ? 'Choose a file first' : (fileError ?? undefined))}
                        data-attr="replace-file-submit"
                    >
                        Replace file
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <LemonField.Pure label="File format" className="w-max">
                    <LemonSelect
                        data-attr="replace-file-format"
                        options={[
                            { label: 'CSV', value: 'csv' },
                            { label: 'JSON', value: 'json' },
                            { label: 'Parquet', value: 'parquet' },
                        ]}
                        value={fileFormat}
                        onChange={setFileFormat}
                        disabledReason={busyReason}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="File" error={fileError ?? undefined} help="Files can be up to 50MB.">
                    <LemonFileInput
                        multiple={false}
                        accept={FILE_UPLOAD_ACCEPT[fileFormat]}
                        value={file ? [file] : []}
                        onChange={(files) => selectFile(files[0] ?? null)}
                        disabledReason={busyReason}
                    />
                </LemonField.Pure>
                {objectStorageSourcesEnabled && (
                    <div className="text-xs text-secondary">
                        Rows imported from this file count toward your data warehouse rows synced.
                    </div>
                )}
                {replaceStage === 'upload' ? (
                    <div className="flex flex-col gap-1" data-attr="replace-file-progress">
                        <LemonProgress percent={uploadPercent} />
                        <div className="text-xs text-secondary">
                            <span>Uploading file:&nbsp;</span>
                            <span translate="no">
                                {uploadPercent}% of {humanizeBytes(file?.size ?? null)}
                            </span>
                        </div>
                    </div>
                ) : replaceStage === 'replace' ? (
                    <div className="flex items-center gap-2 text-xs text-secondary" data-attr="replace-file-progress">
                        <Spinner />
                        <span>File uploaded. Starting the import.</span>
                    </div>
                ) : null}
                {replaceError && <LemonBanner type="error">{replaceError}</LemonBanner>}
            </div>
        </LemonModal>
    )
}
