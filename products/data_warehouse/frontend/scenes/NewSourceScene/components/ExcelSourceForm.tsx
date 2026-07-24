import { useActions, useValues } from 'kea'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { EXCEL_UPLOAD_ACCEPT, excelSourceLogic } from '../excelSourceLogic'
import { sourceWizardLogic } from '../sourceWizardLogic'

/**
 * Replaces the generic connection form for the Excel source: the "credential" here is an uploaded
 * workbook, so the user picks a file and the upload fills the wizard's payload. Everything after
 * this step (sheet selection, column selection, creating the source) is the standard wizard flow.
 */
export function ExcelSourceForm(): JSX.Element {
    const { selectedConnector } = useValues(sourceWizardLogic)
    const { uploading, uploadedFilename } = useValues(excelSourceLogic)
    const { selectFiles } = useActions(excelSourceLogic)

    return (
        <div className="flex flex-col gap-4">
            {selectedConnector?.caption && (
                <LemonMarkdown className="text-sm">{selectedConnector.caption}</LemonMarkdown>
            )}

            <LemonField name="excel_file" label="Workbook">
                <LemonFileInput
                    multiple={false}
                    accept={EXCEL_UPLOAD_ACCEPT}
                    value={[]}
                    onChange={selectFiles}
                    callToAction={
                        <div className="flex items-center gap-2">
                            {uploading ? <Spinner /> : null}
                            <span>{uploading ? 'Uploading…' : 'Choose an .xlsx or .xlsm file'}</span>
                        </div>
                    }
                />
            </LemonField>

            {uploadedFilename && !uploading && (
                <LemonBanner type="success">
                    Uploaded <strong>{uploadedFilename}</strong>. Continue to pick which sheets to import — each one
                    becomes its own table.
                </LemonBanner>
            )}

            {selectedConnector?.docsUrl && (
                <Link to={selectedConnector.docsUrl} target="_blank" className="text-sm">
                    View docs
                </Link>
            )}
        </div>
    )
}
