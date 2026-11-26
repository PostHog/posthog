import { IconDocument, IconUpload } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { cn } from 'lib/utils/css-classes'

import { formatFileSize } from '../../sourceFormUtils'

export function FileSourceDropzone({
    value,
    onChange,
}: {
    value?: File | null
    onChange: (file: File | null) => void
}): JSX.Element {
    return (
        <LemonFileInput
            accept=".pdf,.docx,.md,.markdown,.txt,.csv"
            multiple={false}
            value={value ? [value] : []}
            onChange={(files) => onChange(files[0] ?? null)}
            showUploadedFiles={false}
            callToAction={
                <div
                    className={cn(
                        'flex w-full flex-col items-center gap-2 rounded border border-dashed p-6 text-center',
                        value ? 'border-success' : 'border-primary'
                    )}
                    data-attr="business-knowledge-file-dropzone"
                >
                    {value ? (
                        <>
                            <IconDocument className="text-3xl text-success" />
                            <div className="flex min-w-0 max-w-full flex-col items-center">
                                <span className="font-semibold break-all">{value.name}</span>
                                <span className="text-xs text-secondary" translate="no">
                                    {formatFileSize(value.size)}
                                </span>
                            </div>
                            <LemonButton type="secondary" size="small">
                                Replace file
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            <IconUpload className="text-3xl text-secondary" />
                            <span>Drag a file here</span>
                            <LemonButton type="secondary" size="small">
                                Choose file
                            </LemonButton>
                        </>
                    )}
                </div>
            }
        />
    )
}
