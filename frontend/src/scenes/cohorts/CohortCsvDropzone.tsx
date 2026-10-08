import { IconUpload } from '@posthog/icons'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { cn } from 'lib/utils/css-classes'

export const COHORT_CSV_HELP =
    "Upload a CSV file to add users to your cohort. For single-column files, include one distinct ID per row (all rows will be processed as data). For multi-column files, include a header row with a 'person_id', 'distinct_id', or 'email' column containing the user identifiers."

export function CohortCsvDropzone({
    value,
    onChange,
}: {
    value: File | null
    onChange: (file: File | null) => void
}): JSX.Element {
    return (
        <LemonFileInput
            accept=".csv"
            multiple={false}
            value={value ? [value] : []}
            onChange={(files) => onChange(files[0] ?? null)}
            showUploadedFiles={false}
            callToAction={
                <div
                    className={cn(
                        'flex flex-col items-center justify-center flex-1 cohort-csv-dragger text-text-3000 deprecated-space-y-1',
                        'text-primary mt-0 bg-transparent border border-dashed border-primary hover:border-secondary p-8',
                        value?.name && 'border-success'
                    )}
                >
                    <IconUpload className="text-5xl text-primary" />
                    {value ? (
                        <div>{value.name ?? 'File chosen'}</div>
                    ) : (
                        <>
                            <div>Drag a file here or click to browse for a file</div>
                            <div className="text-secondary text-xs">Accepts .csv files only</div>
                        </>
                    )}
                </div>
            }
        />
    )
}
